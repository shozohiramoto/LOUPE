"""Fiji/ImageJ 1.x RMI IPC (no Fiji instance launch, no startup file edits).

The companion Java 8 class invokes ij.OtherInstance.sendArguments(["-macro",...])
with the *selected Fiji installation's* ij.jar on its classpath.  Both the
native Fiji launcher and Fiji's macros/StartupMacros* remain untouched.

ImageJ's sendArguments() signals argument delivery, NOT image success.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile, BadZipFile


class FijiRMIError(RuntimeError):
    pass


def imagej_jar(executable):
    """Locate this Fiji instance's ImageJ 1.x jar; never choose an arbitrary jar."""
    root = Path(executable).resolve(strict=True).parent
    paths = []
    for where in (root / 'jars', root):
        if where.is_dir():
            paths.extend(where.glob('ij-*.jar'))
            paths.extend(where.glob('ij.jar'))
    # Prefer versioned Fiji jars over unknown PATH and other ImageJ installs.
    for path in sorted(set(paths), key=lambda p: (p.name.lower()=='ij.jar', p.name), reverse=False):
        try:
            with ZipFile(path) as jar:
                if {'ij/OtherInstance.class','ij/ImageJ.class'} <= set(jar.namelist()):
                    return path
        except (OSError,BadZipFile):
            continue
    raise FijiRMIError('ImageJ1 ij.jar not found in the configured Fiji installation')


def java_executable(executable):
    root = Path(executable).resolve(strict=True).parent
    options = []
    for base in (root / 'java' / 'win64', root / 'java' / 'win32', root / 'java'):
        if base.is_dir():
            options += sorted(base.glob('*/bin/java.exe'))
            options += sorted(base.glob('bin/java.exe'))
    for java in options:
        if java.is_file():
            return java
    import shutil
    java = shutil.which('java.exe') or shutil.which('java')
    if java:
        return Path(java)
    raise FijiRMIError('Java runtime was not found in Fiji or PATH')


def rmi_client_class():
    root = Path(__file__).resolve().parents[1]
    result = root / 'tools' / 'java' / 'LoupeOtherInstanceClient.class'
    if not result.is_file():
        raise FijiRMIError('LOUPE ImageJ1 IPC client was not packaged')
    return result.parent


def send_macro_to_existing_fiji(executable, macro_path, *, timeout=12):
    """Return (status, detail). NEVER starts Fiji or changes StartupMacros.

    DELIVERED: ImageJ1 RMI accepted the macro (macro success not confirmed).
    UNAVAILABLE: no RMI stub, disabled RMI, incompatible java, or timeout.
    """
    macro = Path(macro_path).resolve(strict=True)
    if macro.suffix.lower() != '.ijm':
        raise ValueError('LOUPE IPC sends only an internal .ijm macro')
    if sys.platform != 'win32':
        return 'UNAVAILABLE','ImageJ1 RMI integration is supported on Windows'
    try:
        jar=imagej_jar(executable)
        java=java_executable(executable)
        class_dir=rmi_client_class()
        cmd=[str(java),'-Djava.awt.headless=true','-cp',
             os.pathsep.join((str(class_dir),str(jar))),
             'LoupeOtherInstanceClient',str(macro)]
        # CREATE_NO_WINDOW means no extra Java console.  This creates a small
        # helper JVM, NOT another Fiji/ImageJ GUI process.
        completed=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,encoding='utf-8',errors='replace',
                                 timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired,FijiRMIError) as exc:
        return 'UNAVAILABLE',str(exc)[:400]
    message=(completed.stdout or completed.stderr or '').strip()[:400]
    if completed.returncode==0 and 'DELIVERED' in completed.stdout:
        return 'DELIVERED',message
    return 'UNAVAILABLE', message or f'ImageJ1 IPC returned code {completed.returncode}'
