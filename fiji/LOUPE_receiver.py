# LOUPE receiver for Fiji / Jython. Loaded into a running session via ImageJ1 RMI.
# Localhost-only, token-authenticated. Structured OPEN commands only (no
# arbitrary macro execution) plus backward compatible macro paths.
from java.net import ServerSocket, InetAddress, Socket, InetSocketAddress
from java.lang import Thread, Runnable
from java.io import BufferedReader, InputStreamReader, PrintWriter
from java.util import UUID
from java.util.concurrent.atomic import AtomicBoolean
from ij import IJ, ImagePlus, ImageStack
from ij.gui import Line, OvalRoi, Roi, PointRoi
from ij.plugin.frame import RoiManager
import os
import json
import re


def _base():
    home=os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'),'.local','share')
    return os.path.join(home,'LOUPE')


def _bridge_file():return os.path.join(_base(),'fiji_bridge.json')


def _jobs_dir():return os.path.join(_base(),'fiji_jobs')


def _atomic_json(path,obj):
    temp=path+'.tmp'
    with open(temp,'w') as stream:json.dump(obj,stream)
    if os.path.exists(path):os.remove(path)  # Jython 2 / Windows rename rules
    os.rename(temp,path)


def _connected_existing_receiver():
    try:
        with open(_bridge_file()) as f: cfg=json.load(f)
        p=int(cfg['port']);token=cfg['token']
        sock=Socket()
        try:
            sock.connect(InetSocketAddress('127.0.0.1',p),400)
            sock.setSoTimeout(500)
            out=PrintWriter(sock.getOutputStream(),True)
            out.println(token+'\tPING')
            reader=BufferedReader(InputStreamReader(sock.getInputStream(),'UTF-8'))
            return reader.readLine() in ('READY','BUSY')
        finally:sock.close()
    except Exception:return False


def _float(x):
    value=float(x)
    if value!=value or abs(value)>1e9:raise ValueError('Non-finite ROI coordinate')
    return value


def _apply_transfer(image, transfer):
    if not transfer:return []
    if transfer.get('schema')!='loupe_fiji_transfer_v1':
        raise ValueError('Fiji transfer schema not supported')
    if len(transfer.get('rois',[]))>2000:
        raise ValueError('Fiji ROI count limit exceeded')
    warnings=[]
    cal=transfer.get('calibration')
    if cal:
        c=image.getCalibration()
        c.pixelWidth=_float(cal['width_um'])
        c.pixelHeight=_float(cal['height_um'])
        c.setUnit('um')
        image.setCalibration(c)
    contrast=transfer.get('display')
    if contrast:
        lo,hi=_float(contrast['min']),_float(contrast['max'])
        if hi<=lo:raise ValueError('Invalid display range')
        image.setDisplayRange(lo,hi)  # pixel values remain unchanged
        image.updateAndDraw()
    rois=transfer.get('rois',[])
    if rois:
        manager=RoiManager.getInstance()
        if manager is None: manager=RoiManager()
        count=0
        selected_index=None
        for i,item in enumerate(rois):
            kind=item.get('type')
            if kind=='line':
                a,b=item['start'],item['end']
                roi=Line(_float(a[0]),_float(a[1]),_float(b[0]),_float(b[1]))
                width=int(transfer.get('line_width_px',1))
                if width>1:roi.setStrokeWidth(width)
            elif kind=='count':
                p=item['point'];roi=PointRoi(_float(p[0]),_float(p[1]))
            elif kind in ('ellipse','circle','rect'):
                angle=float(item.get('angle',0))
                if abs(angle)>1e-9:
                    warnings.append('Rotated '+kind+' ROI '+str(i+1)+' not transferred (unsupported geometry)')
                    continue
                if kind=='rect':
                    x,y,w,h=item['rect'];roi=Roi(_float(x),_float(y),_float(w),_float(h))
                else:
                    c=item['center']
                    if kind=='circle':
                        d=2*_float(item['radius']);w,h=d,d
                    else:w,h=item['width'],item['height']
                    roi=OvalRoi(_float(c[0])-float(w)/2,_float(c[1])-float(h)/2,
                                _float(w),_float(h))
            else:
                warnings.append('Unknown ROI type '+str(kind));continue
            label=str(item.get('number',i+1)) if kind=='count' else str(i+1)+' '+kind
            roi.setName(label)
            manager.addRoi(roi)
            if item.get('id')==transfer.get('selected_id'):
                selected_index=manager.getCount()-1
            count+=1
        manager.runCommand('Show All')
        if count:
            manager.setVisible(True)
            if selected_index is not None:
                manager.select(selected_index)
    return warnings


class OpenRunner(Runnable):
    def __init__(self, job, busy):self.job,self.busy=job,busy
    def _status(self,status,count=0,error='',warnings=None):
        data={'id':self.job['id'],'status':status,'count':count,'requested':len(self.job['paths'])}
        if error:data['error']=str(error)[:400]
        if warnings:data['warnings']=[str(x)[:200] for x in warnings][:20]
        _atomic_json(os.path.join(_jobs_dir(),self.job['id']+'.status.json'),data)
    def run(self):
        count=0
        try:
            paths=self.job['paths']
            self._status('LOADING',0)
            if len(paths)==1:
                image=IJ.openImage(paths[0])
                if image is None:raise RuntimeError('Fiji could not open TIFF')
                image.show()
                warnings=_apply_transfer(image,self.job.get('transfer'))
                count=1
            else:
                stack=None;first=None
                for i,path in enumerate(paths):
                    source=IJ.openImage(path)
                    if source is None:raise RuntimeError('Cannot load slice '+str(i+1))
                    if source.getStackSize()!=1:
                        raise RuntimeError('Expected one 2D TIFF image per slice')
                    if stack is None:
                        first=source
                        stack=ImageStack(source.getWidth(),source.getHeight())
                    if source.getWidth()!=stack.getWidth() or source.getHeight()!=stack.getHeight():
                        raise RuntimeError('Inconsistent TIFF dimensions at slice '+str(i+1))
                    stack.addSlice(os.path.basename(path),source.getProcessor())
                    count+=1
                    if count%5==0:self._status('LOADING',count)
                image=ImagePlus('LOUPE Stack ('+str(count)+' slices)',stack)
                if first is not None:image.setCalibration(first.getCalibration())
                if image.getStackSize()!=len(paths):
                    raise RuntimeError('Imported Stack count mismatch')
                image.show()
            if len(paths)>1 and self.job.get('transfer'):
                raise ValueError('ROI transfer cannot accompany whole-stack import')
            self._status('COMPLETED',count,warnings=locals().get('warnings',[]))
            for msg in locals().get('warnings',[]):IJ.log('LOUPE transfer warning: '+msg)
            IJ.log('LOUPE import completed: '+str(count)+' / '+str(len(paths))+' slices')
        except Exception as exc:
            self._status('FAILED',count,str(exc))
            IJ.log('LOUPE Fiji import failed: '+str(exc))
        finally:self.busy.set(False)


class MacroRunner(Runnable):
    def __init__(self,path,busy):self.path,self.busy=path,busy
    def run(self):
        try:
            IJ.runMacroFile(self.path)
        except Exception as exc: IJ.log('LOUPE legacy macro error: '+str(exc))
        finally:self.busy.set(False)


class Receiver(Runnable):
    def __init__(self,server,token,busy):self.server,self.token,self.busy=server,token,busy
    def run(self):
        while True:
            client=None
            try:
                client=self.server.accept()
                client.setSoTimeout(1200)
                reader=BufferedReader(InputStreamReader(client.getInputStream(),'UTF-8'))
                writer=PrintWriter(client.getOutputStream(),True)
                payload=reader.readLine()
                if payload is None or len(payload)>8192 or '\t' not in payload:
                    writer.println('INVALID');continue
                token,payload=payload.split('\t',1)
                if token!=self.token:
                    writer.println('INVALID');continue
                if payload=='PING':
                    writer.println('BUSY' if self.busy.get() else 'READY');continue
                if payload=='CAPS':
                    writer.println('TRANSFER_V1');continue
                if not self.busy.compareAndSet(False,True):
                    writer.println('BUSY');continue
                try:
                    if payload.startswith('OPEN\t'):
                        jid=payload[5:]
                        if not re.match(r'^[0-9a-f]{32}$',jid):raise ValueError('Invalid job id')
                        with open(os.path.join(_jobs_dir(),jid+'.request.json')) as f:job=json.load(f)
                        paths=job.get('paths')
                        if (job.get('id')!=jid or job.get('protocol')!=1
                                or not isinstance(paths,list) or not (1<=len(paths)<=15000)):
                            raise ValueError('Invalid request')
                        for path in paths:
                            if (not isinstance(path,basestring) or
                                    not os.path.isabs(path) or
                                    not path.lower().endswith(('.tif','.tiff')) or
                                    not os.path.isfile(path)):
                                raise ValueError('Invalid TIFF path in request')
                        if job.get('transfer') is not None:
                            transfer=job['transfer']
                            if (len(paths)!=1 or not isinstance(transfer,dict) or
                               transfer.get('schema')!='loupe_fiji_transfer_v1'):
                                raise ValueError('Invalid image transfer payload')
                        job['paths']=paths
                        worker=Thread(OpenRunner(job,self.busy),'LOUPE-Fiji-image-import')
                    elif payload.lower().endswith('.ijm') and os.path.isfile(payload):
                        worker=Thread(MacroRunner(payload,self.busy),'LOUPE-Fiji-legacy-macro')
                    else:raise ValueError('Unsupported command')
                    worker.setDaemon(True);worker.start();writer.println('QUEUED')
                except Exception as exc:
                    self.busy.set(False)
                    IJ.log('LOUPE receiver rejected command: '+str(exc))
                    writer.println('INVALID')
            except Exception as exc:
                IJ.log('LOUPE receiver: '+str(exc))
            finally:
                if client is not None:
                    try:client.close()
                    except:pass


if _connected_existing_receiver():
    IJ.log('LOUPE receiver already active (no duplicate listener)')
else:
    server=ServerSocket(0,8,InetAddress.getByName('127.0.0.1'))
    token=str(UUID.randomUUID()).replace('-','')+str(UUID.randomUUID()).replace('-','')
    path=_bridge_file()
    if not os.path.isdir(os.path.dirname(path)):os.makedirs(os.path.dirname(path))
    if not os.path.isdir(_jobs_dir()):os.makedirs(_jobs_dir())
    _atomic_json(path,{'port':int(server.getLocalPort()),'token':token})
    listener=Thread(Receiver(server,token,AtomicBoolean(False)),'LOUPE-Fiji-receiver')
    listener.setDaemon(True);listener.start()
    IJ.log('LOUPE receiver ready on local-only port '+str(server.getLocalPort()))
