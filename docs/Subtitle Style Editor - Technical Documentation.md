Subtitle Style Editor - Technical Documentation

1. Overview & Purpose

The Subtitle Style Editor is an advanced feature integrated into the ManualSelectionDialog. Its purpose is to provide a stable, interactive, and high-fidelity live preview for editing the styles of text-based subtitle tracks (.ass, .ssa, .srt).

The editor allows a user to modify all standard ASS style properties (fonts, colors, sizes, borders, etc.) and see the results rendered directly onto the video in real-time. This ensures that the final merged file's subtitles will look exactly as they do in the preview.

2. Architecture & Technology Stack

The final architecture was chosen after a rigorous process of elimination to overcome a series of bugs and environmental incompatibilities. The primary goal was to find a stable solution that provided 100% accurate, FFmpeg-based subtitle rendering within a PySide6 application on a modern Linux/Wayland environment.

2.1 Core Libraries

    PyAV (Video Decoding & Subtitle Rendering)

        Role: Serves as the Python binding to the core FFmpeg libraries. It is responsible for opening and decoding the reference video file.

        Implementation: To achieve 100% accurate subtitle rendering, we use PyAV's advanced av.filter.Graph API. This allows us to programmatically build an FFmpeg filter chain in memory. We create a graph with three nodes: a buffer (for input video frames), the subtitles filter, and a buffersink (for output frames). Raw video frames are pushed into the graph, and the frames that are pulled from the graph have the subtitles perfectly rendered by FFmpeg's internal libass engine.

    pysubs2 (Subtitle Data Model)

        Role: Acts as the backend for all subtitle data manipulation.

        Implementation: The vsg_core.subtitles.style_engine.py module uses pysubs2 to load the temporary .ass file into an SSAFile object. The UI logic then reads style properties from this object to populate the controls, and writes changes back to it. pysubs2 handles the complexity of parsing and saving the .ass format correctly.

    PySide6 (UI & Frame Display)

        Role: Provides the application's user interface framework.

        Implementation: In the Style Editor, a custom VideoWidget (subclass of QWidget) is used as the video display surface. A QThread runs the PyAV decoding and filtering loop. When a new, subtitle-rendered frame is ready, it is converted to a QImage and sent to the main UI thread via a signal. The VideoWidget receives this QImage and uses a QPainter within its paintEvent to draw the frame, ensuring thread-safe rendering that respects the video's aspect ratio.

2.2 Architectural Journey & Rationale (The "Why")

The final PyAV Filter Graph solution was chosen after several other approaches failed due to specific environmental and library issues:

    Abandoned Approach 1: ffpyplayer with Video Filter

        Reason: This was the initial approach, but it produced a persistent and unfixable TypeError: expected bytes, int found crash when initializing the player with a video filter on the target system. This indicated a fundamental incompatibility between this library's C-interface and the user's environment (modern FFmpeg/Python).

    Abandoned Approach 2: python-vlc

        Reason: The user noted from past experience that embedding a VLC player in a Qt application is unreliable on their modern Linux desktop due to Wayland display server incompatibilities. This path was rejected to avoid known system-level issues.

    Abandoned Approach 3: cython-libass

        Reason: This library would have allowed us to render subtitles separately. However, it could not be installed via pip due to a lack of pre-compiled versions ("wheels") for the user's new Python 3.13 environment. Requiring a local C toolchain and manual compilation was deemed too complex and fragile.

    Abandoned Approach 4: pyvidplayer2

        Reason: Research into this library's documentation and source code revealed that its built-in subtitle support is exclusive to its Pygame backend. The PySide6 backend, while functional for video, does not have any subtitle rendering capabilities.

The PyAV Filter Graph approach was ultimately successful because it provided a stable, installable FFmpeg binding that allowed for the direct, low-level construction of the necessary subtitle filter, bypassing the bugs and limitations of all other libraries.

3. Detailed Feature Breakdown

    Live Video Preview (PlayerThread)

        The PlayerThread manages the PyAV container and filter graph. It runs a loop that decodes a video frame, pushes it through the subtitle filter, pulls the final rendered frame, converts it to a QImage, and emits it to the UI.

        It uses the video's frame rate to implement a time.sleep() for smooth playback timing.

        Audio is explicitly disabled (an=True in older versions, or simply not requested in the PyAV version) to ensure stability and avoid the significant complexity of writing a custom audio/video synchronization engine.

        Seeking is implemented by tearing down and rebuilding the filter graph at the new timestamp, which correctly resets the state.

    On-Demand Font Loading

        Before the Style Editor is launched, the ManualSelectionDialog uses mkvextract to find and extract all font attachments from the source MKV container into a temporary system folder.

        The path to this folder is passed to the PlayerThread, which then adds the :fontsdir='/path/to/fonts' option to the subtitles filter arguments. This allows the FFmpeg renderer to find and use the correct embedded fonts for a pixel-perfect preview.

    Interactive Style Editing & Live Updates

        When a style property is changed in the UI, the StyleEditorLogic updates the in-memory pysubs2 object and saves it to the temporary .ass file.

        It then signals the PlayerThread to reload the subtitle track. The thread sees this request and rebuilds its filter graph, causing the video preview to update with the new styles.

        For smoother UI interaction, updates from spin boxes are triggered by editingFinished, while other controls update instantly.

    Override Tag Handling

        Warning System: When a user selects a dialogue line, the logic checks the raw text for {\...} blocks. If found, a warning is displayed in the UI to inform the user that their global style edits might be overridden.

        "Smart Strip" Feature: A button allows the user to strip tags from selected lines. This feature uses a targeted regular expression to remove only style-related tags (\c, \fs, \b, \bord, etc.) while preserving essential layout and animation tags (\pos, \move, \fad, etc.).

    Style Management & Resampling

        Reset Style: The editor stores the original styles on load, and a "Reset Style" button allows the user to revert the current style to its original state.

        Resampling: A "Resample..." button opens a dialog to change the script's PlayResX/PlayResY resolution. It can auto-populate the video's native resolution using ffprobe. The change is applied instantly to the preview.
