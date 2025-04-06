pub mod rapl;

#[no_mangle]
pub extern "C" fn start_rapl() -> i32 {
    rapl::start_rapl()
}

#[no_mangle]
pub extern "C" fn stop_rapl() {
    rapl::stop_rapl();
}

// JNI interface for Java
#[cfg(target_os = "linux")]
#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
pub mod jni {
    use jni::objects::{JClass};
    use jni::sys::jint;
    use jni::JNIEnv;

    #[no_mangle]
    pub extern "system" fn Java_RaplInterface_startRapl(
        _env: JNIEnv,
        _class: JClass,
    ) -> jint {
        crate::rapl::start_rapl()
    }

    #[no_mangle]
    pub extern "system" fn Java_RaplInterface_stopRapl(
        _env: JNIEnv,
        _class: JClass,
    ) {
        crate::rapl::stop_rapl();
    }
}
