# Qt + CXX Migration Plan

Migration from Slint to Qt/C++ with CXX bridge, maintaining the same separation of UI and logic.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Qt C++ UI (qt_ui/)                                         │
│  - Mirrors original PySide structure                        │
│  - System theme (Breeze Dark) - no custom styling needed    │
├─────────────────────────────────────────────────────────────┤
│  CXX Bridge (crates/vsg_bridge/)                            │
│  - Safe Rust <-> C++ FFI                                    │
│  - Exposes vsg_core to Qt                                   │
├─────────────────────────────────────────────────────────────┤
│  Rust Backend (crates/vsg_core/) - UNCHANGED                │
│  - Config, models, orchestrator, mux builder                │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
video-sync-gui/
├── Cargo.toml                      # Workspace (add vsg_bridge)
│
├── crates/
│   ├── vsg_core/                   # UNCHANGED
│   │
│   ├── vsg_bridge/                 # NEW - CXX bridge
│   │   ├── Cargo.toml
│   │   ├── build.rs
│   │   ├── src/
│   │   │   ├── lib.rs              # CXX bridge definitions
│   │   │   ├── config.rs           # Config bridge functions
│   │   │   ├── pipeline.rs         # Pipeline/job bridge functions
│   │   │   └── types.rs            # Shared type conversions
│   │   └── include/
│   │       └── vsg_bridge.hpp      # C++ header (generated + manual)
│   │
│   └── vsg_ui/                     # KEEP for reference, will be replaced
│
├── qt_ui/                          # NEW - Qt C++ application
│   ├── CMakeLists.txt
│   │
│   ├── main_window/                # Per-window folders (like PySide)
│   │   ├── window.hpp              # UI shell
│   │   ├── window.cpp
│   │   ├── controller.hpp          # Logic
│   │   └── controller.cpp
│   │
│   ├── job_queue_dialog/
│   │   ├── ui.hpp/cpp
│   │   └── logic.hpp/cpp
│   │
│   ├── add_job_dialog/
│   │   └── ui.hpp/cpp
│   │
│   ├── manual_selection_dialog/
│   │   ├── ui.hpp/cpp
│   │   ├── logic.hpp/cpp
│   │   └── widgets.hpp/cpp         # TrackWidget, SourceGroup, etc.
│   │
│   ├── track_settings_dialog/
│   │   ├── ui.hpp/cpp
│   │   └── logic.hpp/cpp
│   │
│   ├── options_dialog/             # Settings
│   │   ├── ui.hpp/cpp
│   │   ├── logic.hpp/cpp
│   │   └── tabs.hpp/cpp
│   │
│   ├── track_widget/               # Reusable component
│   │   ├── ui.hpp/cpp
│   │   ├── logic.hpp/cpp
│   │   └── helpers.hpp/cpp
│   │
│   ├── worker/                     # Background job execution
│   │   ├── runner.hpp/cpp
│   │   └── signals.hpp/cpp
│   │
│   ├── common/                     # Shared utilities
│   │   ├── file_dialogs.hpp/cpp
│   │   └── drag_drop.hpp/cpp
│   │
│   └── main.cpp                    # Entry point
│
└── Reference Only original/        # Keep for reference
```

## Phase 1: Foundation Setup

### 1.1 Create vsg_bridge Crate

**Cargo.toml:**
```toml
[package]
name = "vsg_bridge"
version = "0.1.0"
edition = "2024"

[lib]
crate-type = ["staticlib"]

[dependencies]
vsg_core = { path = "../vsg_core" }
cxx = "1.0"

[build-dependencies]
cxx-build = "1.0"
```

**src/lib.rs - Initial bridge:**
```rust
#[cxx::bridge]
mod ffi {
    // Shared types between Rust and C++
    #[derive(Debug, Clone)]
    struct BridgeConfig {
        output_folder: String,
        temp_folder: String,
        logs_folder: String,
        // ... other config fields
    }

    #[derive(Debug, Clone)]
    struct AnalysisResult {
        delay_ms: f64,
        confidence: f64,
        success: bool,
        error_message: String,
    }

    #[derive(Debug, Clone)]
    struct SourcePaths {
        paths: Vec<String>,
    }

    // Rust functions exposed to C++
    extern "Rust" {
        fn bridge_load_config() -> BridgeConfig;
        fn bridge_save_config(config: &BridgeConfig);
        fn bridge_run_analysis(sources: &SourcePaths) -> Vec<AnalysisResult>;
        fn bridge_discover_jobs(paths: &[String]) -> Vec<String>; // JSON for now
    }

    // C++ functions Rust can call (callbacks)
    unsafe extern "C++" {
        include!("vsg_bridge.hpp");

        type Callbacks;
        fn on_log_message(self: &Callbacks, message: &str);
        fn on_progress(self: &Callbacks, percent: i32, status: &str);
    }
}
```

### 1.2 Create Qt Project Structure

**CMakeLists.txt:**
```cmake
cmake_minimum_required(VERSION 3.20)
project(video-sync-gui LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Find Qt6
find_package(Qt6 REQUIRED COMPONENTS Widgets)

# Use Corrosion to build Rust crates
include(FetchContent)
FetchContent_Declare(
    Corrosion
    GIT_REPOSITORY https://github.com/corrosion-rs/corrosion.git
    GIT_TAG v0.5
)
FetchContent_MakeAvailable(Corrosion)

# Import Rust bridge crate
corrosion_import_crate(MANIFEST_PATH ../Cargo.toml CRATES vsg_bridge)

# Collect sources
set(SOURCES
    main.cpp
    main_window/window.cpp
    main_window/controller.cpp
    common/file_dialogs.cpp
)

add_executable(${PROJECT_NAME} ${SOURCES})

target_link_libraries(${PROJECT_NAME}
    Qt6::Widgets
    vsg_bridge
)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../crates/vsg_bridge/include
)
```

## Phase 2: Main Window (MVP)

### 2.1 Main Window UI Shell

**main_window/window.hpp:**
```cpp
#pragma once
#include <QMainWindow>
#include <QLineEdit>
#include <QTextEdit>
#include <QProgressBar>
#include <QLabel>
#include <QPushButton>
#include <QCheckBox>
#include <vector>

class MainController;  // Forward declare

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    // Public widget access for controller
    QLineEdit* refInput() { return m_refInput; }
    QLineEdit* secInput() { return m_secInput; }
    QLineEdit* terInput() { return m_terInput; }
    QTextEdit* logOutput() { return m_logOutput; }
    QProgressBar* progressBar() { return m_progressBar; }
    QLabel* statusLabel() { return m_statusLabel; }
    QCheckBox* archiveLogsCheck() { return m_archiveLogsCheck; }
    std::vector<QLabel*>& delayLabels() { return m_delayLabels; }

private:
    void buildUi();
    QLayout* createFileInput(const QString& label, QLineEdit* input,
                             std::function<void()> browseCallback);

    // Widgets
    QLineEdit* m_refInput;
    QLineEdit* m_secInput;
    QLineEdit* m_terInput;
    QTextEdit* m_logOutput;
    QProgressBar* m_progressBar;
    QLabel* m_statusLabel;
    QPushButton* m_optionsBtn;
    QPushButton* m_queueJobsBtn;
    QCheckBox* m_archiveLogsCheck;
    std::vector<QLabel*> m_delayLabels;

    // Controller (owns logic)
    std::unique_ptr<MainController> m_controller;
};
```

**main_window/window.cpp:**
```cpp
#include "window.hpp"
#include "controller.hpp"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGroupBox>

MainWindow::MainWindow(QWidget* parent)
    : QMainWindow(parent)
{
    setWindowTitle("Video/Audio Sync & Merge");
    setGeometry(100, 100, 1000, 600);

    buildUi();

    m_controller = std::make_unique<MainController>(this);
    m_controller->applyConfigToUi();

    // Wire signals to controller
    connect(m_optionsBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::openOptionsDialog);
    connect(m_queueJobsBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::openJobQueue);
}

void MainWindow::buildUi() {
    auto* central = new QWidget(this);
    setCentralWidget(central);
    auto* mainLayout = new QVBoxLayout(central);

    // Top row - Settings button
    auto* topRow = new QHBoxLayout();
    m_optionsBtn = new QPushButton("Settings...");
    topRow->addWidget(m_optionsBtn);
    topRow->addStretch();
    mainLayout->addLayout(topRow);

    // Main Workflow group
    auto* actionsGroup = new QGroupBox("Main Workflow");
    auto* actionsLayout = new QVBoxLayout(actionsGroup);
    m_queueJobsBtn = new QPushButton("Open Job Queue for Merging...");
    m_queueJobsBtn->setStyleSheet("font-size: 14px; padding: 5px;");
    actionsLayout->addWidget(m_queueJobsBtn);
    m_archiveLogsCheck = new QCheckBox("Archive logs to a zip file on batch completion");
    actionsLayout->addWidget(m_archiveLogsCheck);
    mainLayout->addWidget(actionsGroup);

    // Quick Analysis group
    auto* analysisGroup = new QGroupBox("Quick Analysis (Analyze Only)");
    auto* analysisLayout = new QVBoxLayout(analysisGroup);

    m_refInput = new QLineEdit();
    m_secInput = new QLineEdit();
    m_terInput = new QLineEdit();

    analysisLayout->addLayout(createFileInput("Source 1 (Reference):", m_refInput,
        [this]() { m_controller->browseForPath(m_refInput, "Select Reference File"); }));
    analysisLayout->addLayout(createFileInput("Source 2:", m_secInput,
        [this]() { m_controller->browseForPath(m_secInput, "Select Secondary File"); }));
    analysisLayout->addLayout(createFileInput("Source 3:", m_terInput,
        [this]() { m_controller->browseForPath(m_terInput, "Select Tertiary File"); }));

    auto* analyzeBtn = new QPushButton("Analyze Only");
    connect(analyzeBtn, &QPushButton::clicked,
            m_controller.get(), &MainController::startAnalyzeOnly);
    analysisLayout->addWidget(analyzeBtn, 0, Qt::AlignRight);
    mainLayout->addWidget(analysisGroup);

    // Status row
    auto* statusLayout = new QHBoxLayout();
    statusLayout->addWidget(new QLabel("Status:"));
    m_statusLabel = new QLabel("Ready");
    statusLayout->addWidget(m_statusLabel, 1);
    m_progressBar = new QProgressBar();
    m_progressBar->setRange(0, 100);
    statusLayout->addWidget(m_progressBar);
    mainLayout->addLayout(statusLayout);

    // Results group
    auto* resultsGroup = new QGroupBox("Latest Job Results");
    auto* resultsLayout = new QHBoxLayout(resultsGroup);
    for (int i = 2; i <= 4; ++i) {
        resultsLayout->addWidget(new QLabel(QString("Source %1 Delay:").arg(i)));
        auto* delayLabel = new QLabel("--");
        m_delayLabels.push_back(delayLabel);
        resultsLayout->addWidget(delayLabel);
        resultsLayout->addSpacing(20);
    }
    resultsLayout->addStretch();
    mainLayout->addWidget(resultsGroup);

    // Log group
    auto* logGroup = new QGroupBox("Log");
    auto* logLayout = new QVBoxLayout(logGroup);
    m_logOutput = new QTextEdit();
    m_logOutput->setReadOnly(true);
    m_logOutput->setFontFamily("monospace");
    logLayout->addWidget(m_logOutput);
    mainLayout->addWidget(logGroup);
}

QLayout* MainWindow::createFileInput(const QString& label, QLineEdit* input,
                                      std::function<void()> browseCallback) {
    auto* layout = new QHBoxLayout();
    layout->addWidget(new QLabel(label));
    layout->addWidget(input, 1);
    auto* browseBtn = new QPushButton("Browse...");
    connect(browseBtn, &QPushButton::clicked, browseCallback);
    layout->addWidget(browseBtn);
    return layout;
}
```

### 2.2 Main Window Controller

**main_window/controller.hpp:**
```cpp
#pragma once
#include <QObject>
#include <QString>

class MainWindow;
class QLineEdit;

class MainController : public QObject {
    Q_OBJECT

public:
    explicit MainController(MainWindow* view);

public slots:
    void openOptionsDialog();
    void openJobQueue();
    void startAnalyzeOnly();
    void browseForPath(QLineEdit* lineEdit, const QString& caption);

    // Callbacks from bridge
    void appendLog(const QString& message);
    void updateProgress(int percent);
    void updateStatus(const QString& status);

private:
    void applyConfigToUi();
    void saveUiToConfig();

    MainWindow* m_view;
    // Bridge handle would go here
};
```

## Phase 3: Bridge Integration

### 3.1 Connect Config

```rust
// vsg_bridge/src/config.rs
use vsg_core::config::AppConfig;

pub fn bridge_load_config() -> ffi::BridgeConfig {
    let config = AppConfig::load().unwrap_or_default();
    ffi::BridgeConfig {
        output_folder: config.get_string("output_folder").unwrap_or_default(),
        temp_folder: config.get_string("temp_folder").unwrap_or_default(),
        logs_folder: config.get_string("logs_folder").unwrap_or_default(),
        // ... map other fields
    }
}

pub fn bridge_save_config(config: &ffi::BridgeConfig) {
    let mut app_config = AppConfig::load().unwrap_or_default();
    app_config.set("output_folder", &config.output_folder);
    app_config.set("temp_folder", &config.temp_folder);
    app_config.set("logs_folder", &config.logs_folder);
    app_config.save().ok();
}
```

### 3.2 Connect Pipeline

```rust
// vsg_bridge/src/pipeline.rs
use vsg_core::orchestrator::Orchestrator;

pub fn bridge_run_analysis(
    sources: &ffi::SourcePaths,
    callbacks: &ffi::Callbacks
) -> Vec<ffi::AnalysisResult> {
    let orchestrator = Orchestrator::new();

    // Set up callback forwarding
    orchestrator.set_log_callback(|msg| {
        callbacks.on_log_message(&msg);
    });

    orchestrator.set_progress_callback(|pct, status| {
        callbacks.on_progress(pct as i32, &status);
    });

    // Run analysis
    match orchestrator.analyze_only(&sources.paths) {
        Ok(results) => results.into_iter().map(|r| ffi::AnalysisResult {
            delay_ms: r.delay_ms,
            confidence: r.confidence,
            success: true,
            error_message: String::new(),
        }).collect(),
        Err(e) => vec![ffi::AnalysisResult {
            delay_ms: 0.0,
            confidence: 0.0,
            success: false,
            error_message: e.to_string(),
        }],
    }
}
```

## Phase 4: Port Remaining Windows

Order of implementation (based on dependencies):

1. **OptionsDialog** (settings) - needed early for config
2. **AddJobDialog** - simple, needed for job queue
3. **JobQueueDialog** - core workflow
4. **TrackWidget** - reusable component
5. **ManualSelectionDialog** - complex but needed for job config
6. **TrackSettingsDialog** - per-track options

Each window follows same pattern:
- `ui.hpp/cpp` = widget creation, layout (no logic)
- `logic.hpp/cpp` = event handlers, bridge calls, state

## Phase 5: Build & Run

### Build Commands

```bash
# From project root
cd qt_ui
mkdir build && cd build
cmake ..
make -j$(nproc)

# Run
./video-sync-gui
```

### Dependencies (Fedora/KDE)

```bash
sudo dnf install qt6-qtbase-devel cmake ninja-build
# Rust toolchain already installed
```

## Migration Checklist

- [ ] Create vsg_bridge crate structure
- [ ] Set up CMake with Corrosion
- [ ] Implement basic CXX bridge (config load/save)
- [ ] Create MainWindow UI shell
- [ ] Create MainController with bridge calls
- [ ] Verify build and basic functionality
- [ ] Port OptionsDialog
- [ ] Port AddJobDialog
- [ ] Port JobQueueDialog
- [ ] Port TrackWidget component
- [ ] Port ManualSelectionDialog
- [ ] Port TrackSettingsDialog
- [ ] Wire up full pipeline (analyze + merge)
- [ ] Test drag-and-drop
- [ ] Test all dialogs
- [ ] Remove/archive Slint code

## Notes

- Keep vsg_ui (Slint) until Qt version is functional
- Reference PySide code for exact UI layout/behavior
- CXX handles memory safety at boundary
- Qt signals/slots map directly to PySide pattern
- System theme (Breeze Dark) handles all styling
