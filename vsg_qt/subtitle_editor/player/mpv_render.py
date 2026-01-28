# vsg_qt/subtitle_editor/player/mpv_render.py
# -*- coding: utf-8 -*-
"""
MPV render context bindings for Qt OpenGL integration.

Adds the render API that's missing from python-mpv, allowing MPV to render
directly into a Qt OpenGL widget. Works on native Wayland.

Based on FeelUOwn's implementation.
"""
from ctypes import (
    CFUNCTYPE, POINTER, Structure, byref, cast, c_void_p, c_int, c_int64,
    c_char_p, create_string_buffer, sizeof, pointer
)
from ctypes.util import find_library
import ctypes
import os


# Load libmpv
def _load_libmpv():
    """Load the libmpv shared library."""
    # Try common library names
    lib_names = ['mpv', 'libmpv.so.2', 'libmpv.so.1', 'libmpv.so', 'mpv-2.dll', 'mpv-1.dll']

    for name in lib_names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            pass

    # Try find_library
    lib_path = find_library('mpv')
    if lib_path:
        return ctypes.CDLL(lib_path)

    raise OSError("Could not find libmpv. Make sure mpv is installed.")


_lib = _load_libmpv()


# Type definitions
class MpvHandle(c_void_p):
    """Handle to an mpv instance."""
    pass


class MpvRenderCtxHandle(c_void_p):
    """Handle to an mpv render context."""
    pass


# Callback types
MpvGlGetProcAddressFn = CFUNCTYPE(c_void_p, c_void_p, c_char_p)
OpenGlCbGetProcAddrFn = CFUNCTYPE(c_void_p, c_void_p, c_char_p)
RenderUpdateFn = CFUNCTYPE(None, c_void_p)


# Structures for OpenGL rendering
class MpvOpenGLInitParams(Structure):
    """Parameters for OpenGL initialization."""
    _fields_ = [
        ('get_proc_address', MpvGlGetProcAddressFn),
        ('get_proc_address_ctx', c_void_p),
        ('extra_exts', c_void_p)
    ]

    def __init__(self, get_proc_address=None, ctx=None):
        super().__init__()
        if get_proc_address:
            self.get_proc_address = get_proc_address
        self.get_proc_address_ctx = ctx
        self.extra_exts = None


class MpvOpenGLFBO(Structure):
    """Framebuffer object specification."""
    _fields_ = [
        ('fbo', c_int),
        ('w', c_int),
        ('h', c_int),
        ('internal_format', c_int)
    ]

    def __init__(self, w=0, h=0, fbo=0, internal_format=0):
        super().__init__()
        self.w = w
        self.h = h
        self.fbo = fbo
        self.internal_format = internal_format


class MpvRenderParam(Structure):
    """Render parameter for the render API."""
    _fields_ = [
        ('type_id', c_int),
        ('data', c_void_p)
    ]

    # Parameter type IDs
    TYPES = {
        'invalid': (0, None),
        'api_type': (1, c_char_p),
        'opengl_init_params': (2, MpvOpenGLInitParams),
        'opengl_fbo': (3, MpvOpenGLFBO),
        'flip_y': (4, c_int),
        'depth': (5, c_int),
        'icc_profile': (6, c_void_p),
        'ambient_light': (7, c_int),
        'x11_display': (8, c_void_p),
        'wl_display': (9, c_void_p),
        'advanced_control': (10, c_int),
        'next_frame_info': (11, c_void_p),
        'block_for_target_time': (12, c_int),
        'skip_rendering': (13, c_int),
    }

    def __init__(self, name=None, value=None):
        super().__init__()
        if name is None:
            self.type_id = 0
            self.data = None
            return

        if name not in self.TYPES:
            raise ValueError(f"Unknown render param: {name}")

        type_id, data_type = self.TYPES[name]
        self.type_id = type_id

        if value is None:
            self.data = None
        elif data_type is None:
            self.data = None
        elif data_type == c_char_p:
            if isinstance(value, str):
                value = value.encode('utf-8')
            self.data = cast(c_char_p(value), c_void_p)
        elif data_type == c_int:
            val = c_int(int(value))
            self.data = cast(pointer(val), c_void_p)
        elif data_type in (MpvOpenGLInitParams, MpvOpenGLFBO):
            self.data = cast(pointer(value), c_void_p)
        else:
            self.data = cast(value, c_void_p)


def _make_render_param_array(params):
    """Convert dict of params to array of MpvRenderParam."""
    arr_type = MpvRenderParam * (len(params) + 1)
    arr = arr_type()

    for i, (name, value) in enumerate(params.items()):
        arr[i] = MpvRenderParam(name, value)

    # Terminator
    arr[len(params)] = MpvRenderParam('invalid', None)

    return arr


# Error checking
def _check_error(result, func, args):
    """Error check for mpv functions."""
    if result < 0:
        raise RuntimeError(f"MPV error: {result}")
    return result


# Define mpv render API functions
_mpv_render_context_create = _lib.mpv_render_context_create
_mpv_render_context_create.argtypes = [POINTER(MpvRenderCtxHandle), MpvHandle, POINTER(MpvRenderParam)]
_mpv_render_context_create.restype = c_int
_mpv_render_context_create.errcheck = _check_error

_mpv_render_context_set_update_callback = _lib.mpv_render_context_set_update_callback
_mpv_render_context_set_update_callback.argtypes = [MpvRenderCtxHandle, RenderUpdateFn, c_void_p]
_mpv_render_context_set_update_callback.restype = None

_mpv_render_context_update = _lib.mpv_render_context_update
_mpv_render_context_update.argtypes = [MpvRenderCtxHandle]
_mpv_render_context_update.restype = c_int64

_mpv_render_context_render = _lib.mpv_render_context_render
_mpv_render_context_render.argtypes = [MpvRenderCtxHandle, POINTER(MpvRenderParam)]
_mpv_render_context_render.restype = c_int
_mpv_render_context_render.errcheck = _check_error

_mpv_render_context_report_swap = _lib.mpv_render_context_report_swap
_mpv_render_context_report_swap.argtypes = [MpvRenderCtxHandle]
_mpv_render_context_report_swap.restype = None

_mpv_render_context_free = _lib.mpv_render_context_free
_mpv_render_context_free.argtypes = [MpvRenderCtxHandle]
_mpv_render_context_free.restype = None


class MpvRenderContext:
    """
    MPV render context for OpenGL rendering.

    Allows MPV to render directly into an OpenGL framebuffer,
    enabling integration with Qt OpenGL widgets.
    """

    def __init__(self, mpv_instance, api_type='opengl', **kwargs):
        """
        Create a render context.

        Args:
            mpv_instance: An MPV instance (from python-mpv)
            api_type: API type, usually 'opengl'
            **kwargs: Render parameters (opengl_init_params, etc.)
        """
        self._mpv = mpv_instance
        self._update_cb = None
        self._update_fn_wrapper = None

        # Add api_type to params
        kwargs['api_type'] = api_type

        # Create render context
        ctx_handle = MpvRenderCtxHandle()
        params = _make_render_param_array(kwargs)

        _mpv_render_context_create(
            byref(ctx_handle),
            MpvHandle(mpv_instance.handle.value if hasattr(mpv_instance.handle, 'value') else mpv_instance.handle),
            params
        )

        self._handle = ctx_handle
        print(f"[MpvRenderContext] Created render context")

    @property
    def handle(self):
        """Get the raw handle."""
        return self._handle

    @property
    def update_cb(self):
        """Get the update callback."""
        return self._update_cb

    @update_cb.setter
    def update_cb(self, callback):
        """Set the update callback - called when a new frame is ready."""
        self._update_cb = callback

        if callback:
            # Wrap callback to match C signature
            def wrapper(ctx):
                callback()
            self._update_fn_wrapper = RenderUpdateFn(wrapper)
        else:
            self._update_fn_wrapper = RenderUpdateFn(lambda ctx: None)

        _mpv_render_context_set_update_callback(
            self._handle,
            self._update_fn_wrapper,
            None
        )

    def update(self):
        """
        Check if a new frame is available.

        Returns:
            True if a new frame should be rendered
        """
        flags = _mpv_render_context_update(self._handle)
        return bool(flags & 1)

    def render(self, flip_y=True, opengl_fbo=None, **kwargs):
        """
        Render a frame to the specified FBO.

        Args:
            flip_y: Whether to flip the image vertically
            opengl_fbo: Dict with 'fbo', 'w', 'h' keys, or MpvOpenGLFBO instance
            **kwargs: Additional render parameters
        """
        params = {}

        if flip_y:
            params['flip_y'] = 1

        if opengl_fbo:
            if isinstance(opengl_fbo, dict):
                fbo = MpvOpenGLFBO(
                    w=opengl_fbo.get('w', 0),
                    h=opengl_fbo.get('h', 0),
                    fbo=opengl_fbo.get('fbo', 0),
                    internal_format=opengl_fbo.get('internal_format', 0)
                )
            else:
                fbo = opengl_fbo
            params['opengl_fbo'] = fbo

        params.update(kwargs)

        param_array = _make_render_param_array(params)
        _mpv_render_context_render(self._handle, param_array)

    def report_swap(self):
        """Report that a buffer swap has occurred."""
        _mpv_render_context_report_swap(self._handle)

    def free(self):
        """Free the render context."""
        if self._handle:
            _mpv_render_context_free(self._handle)
            self._handle = None
            print(f"[MpvRenderContext] Freed render context")

    def __del__(self):
        """Destructor."""
        self.free()
