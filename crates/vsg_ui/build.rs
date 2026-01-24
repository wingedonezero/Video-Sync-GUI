fn main() {
    // Enable experimental features for drag-and-drop support
    std::env::set_var("SLINT_ENABLE_EXPERIMENTAL_FEATURES", "1");

    slint_build::compile("slint/app.slint").expect("Slint UI build failed");
}
