/*
 * Minimal Java 8 ImageJ1 RMI client. Uses the configured Fiji's ij.jar at
 * runtime; it does not launch any ImageJ main class or open a Fiji GUI.
 * Compile: javac --release 8 -d tools/java tools/java/LoupeOtherInstanceClient.java
 */
import java.io.File;
import java.lang.reflect.Method;

public final class LoupeOtherInstanceClient {
    public static void main(String[] args) {
        if (args.length != 1 || !new File(args[0]).isFile() || !args[0].toLowerCase().endsWith(".ijm")) {
            System.out.println("INVALID_MACRO"); System.exit(20); return;
        }
        try {
            Class<?> client = Class.forName("ij.OtherInstance");
            // Check the expected stub BEFORE sendArguments(). Avoid invoking its
            // startServer() branch merely because no Fiji listener exists.
            Method stubPath = client.getDeclaredMethod("getStubPath");
            stubPath.setAccessible(true);
            File stub = new File((String) stubPath.invoke(null));
            if (!stub.isFile()) {
                System.out.println("RMI_STUB_ABSENT"); System.exit(10); return;
            }
            Method enabled = client.getDeclaredMethod("isRMIEnabled");
            enabled.setAccessible(true);
            if (!Boolean.TRUE.equals(enabled.invoke(null))) {
                System.out.println("RMI_DISABLED"); System.exit(11); return;
            }
            Method send = client.getMethod("sendArguments", String[].class);
            Boolean delivered = (Boolean) send.invoke(null, (Object) new String[]{"-macro", args[0]});
            System.out.println(Boolean.TRUE.equals(delivered) ? "DELIVERED" : "RMI_NOT_DELIVERED");
            System.exit(Boolean.TRUE.equals(delivered) ? 0 : 12);
        } catch (Throwable e) {
            System.out.println("RMI_FAILURE: " + e.getClass().getSimpleName());
            System.exit(13);
        }
    }
}
