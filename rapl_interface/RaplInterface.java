public class RaplInterface {
    static {
        System.loadLibrary("rapl_interface");
    }

    public native int startRapl();

    public native void stopRapl();
}
