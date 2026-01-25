// Video Sync GUI - Qt Edition
// Main entry point

#include <QApplication>
#include "main_window/window.hpp"

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);

    // Set application metadata
    QApplication::setApplicationName("Video Sync GUI");
    QApplication::setOrganizationName("VideoSyncGUI");
    QApplication::setApplicationVersion("0.1.0");

    // Create and show main window
    MainWindow mainWindow;
    mainWindow.show();

    return app.exec();
}
