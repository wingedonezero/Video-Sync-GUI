// Video Sync GUI - Qt Edition
// Main entry point

#include <QApplication>
#include <QDir>
#include "main_window/window.hpp"
#include "bridge/vsg_bridge.hpp"

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);

    // Set application metadata
    QApplication::setApplicationName("Video Sync GUI");
    QApplication::setOrganizationName("VideoSyncGUI");
    QApplication::setApplicationVersion("0.1.0");

    // Initialize bridge (sets up logging to .logs/app.log and GUI)
    // Uses current working directory for logs
    QString logsDir = QDir::currentPath() + "/.logs";
    VsgBridge::init(logsDir);

    // Create and show main window
    MainWindow mainWindow;
    mainWindow.show();

    return app.exec();
}
