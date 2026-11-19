//! The Wayland desktop: its pictures (wlr-screencopy, the cursor drawn in) and input into it (wlr-virtual-pointer
//! and the virtual keyboard). Hyprland, sway and the other wlroots-family compositors have all three.

use std::ffi::CStr;
use std::os::fd::{AsFd, OwnedFd};

use rustix::fs::{ftruncate, memfd_create, MemfdFlags};
use rustix::event::{PollFd, PollFlags, Timespec};
use rustix::mm::{mmap, munmap, MapFlags, ProtFlags};
use wayland_client::globals::{registry_queue_init, GlobalListContents};
use wayland_client::protocol::{wl_buffer, wl_keyboard, wl_output, wl_pointer, wl_registry, wl_seat, wl_shm, wl_shm_pool};
use wayland_client::{delegate_noop, Connection, Dispatch, EventQueue, Proxy, QueueHandle, WEnum};
use wayland_protocols_misc::zwp_virtual_keyboard_v1::client::{zwp_virtual_keyboard_manager_v1, zwp_virtual_keyboard_v1};
use wayland_protocols_wlr::screencopy::v1::client::{zwlr_screencopy_frame_v1, zwlr_screencopy_manager_v1};
use wayland_protocols_wlr::virtual_pointer::v1::client::{zwlr_virtual_pointer_manager_v1, zwlr_virtual_pointer_v1};

#[derive(Default, Clone, Debug)]
pub struct OutputInfo {
    pub name: String,
    pub width: i32,
    pub height: i32,
}

#[derive(Default)]
struct FrameState {
    format: Option<(WEnum<wl_shm::Format>, u32, u32, u32)>,
    buffer_done: bool,
    ready: bool,
    failed: bool,
    y_invert: bool,
}

struct State {
    outputs: Vec<(wl_output::WlOutput, OutputInfo)>,
    frame: FrameState,
    keymap: Option<String>,
}

/// One captured picture: tightly packed rows, 4 bytes a pixel.
pub struct Picture {
    pub width: u32,
    pub height: u32,
    /// true: the bytes are B, G, R, X (XRGB8888 in memory); false: R, G, B, X.
    pub bgr: bool,
    pub pixels: Vec<u8>,
}

struct ShmBuffer {
    buffer: wl_buffer::WlBuffer,
    pool: wl_shm_pool::WlShmPool,
    _fd: OwnedFd,
    ptr: *mut core::ffi::c_void,
    len: usize,
    key: (u32, u32, u32, u32),
}

impl Drop for ShmBuffer {
    fn drop(&mut self) {
        self.buffer.destroy();
        self.pool.destroy();
        unsafe {
            let _ = munmap(self.ptr, self.len);
        }
    }
}

pub struct Desktop {
    _conn: Connection,
    queue: EventQueue<State>,
    qh: QueueHandle<State>,
    state: State,
    shm: wl_shm::WlShm,
    screencopy: zwlr_screencopy_manager_v1::ZwlrScreencopyManagerV1,
    output: usize,
    pointer: Option<zwlr_virtual_pointer_v1::ZwlrVirtualPointerV1>,
    keyboard: Option<zwp_virtual_keyboard_v1::ZwpVirtualKeyboardV1>,
    buffer: Option<ShmBuffer>,
    pending: Option<(zwlr_screencopy_frame_v1::ZwlrScreencopyFrameV1, bool)>,
    picture: Option<Picture>,
    mods: Modifiers,
    start: std::time::Instant,
    conn: Connection,
}

#[derive(Default)]
struct Modifiers {
    shift: u8,
    ctrl: u8,
    alt: u8,
    logo: u8,
    altgr: u8,
    caps: bool,
}

impl Modifiers {
    /// The standard xkb modifier masks: Shift 1, Lock 2, Control 4, Mod1 (Alt) 8, Mod4 (Super) 64, Mod5 (AltGr) 128.
    fn depressed(&self) -> u32 {
        (if self.shift > 0 { 1 } else { 0 })
            | (if self.ctrl > 0 { 4 } else { 0 })
            | (if self.alt > 0 { 8 } else { 0 })
            | (if self.logo > 0 { 64 } else { 0 })
            | (if self.altgr > 0 { 128 } else { 0 })
    }

    fn update(&mut self, key: u32, pressed: bool) -> bool {
        let slot = match key {
            42 | 54 => &mut self.shift,
            29 | 97 => &mut self.ctrl,
            56 => &mut self.alt,
            125 | 126 => &mut self.logo,
            100 => &mut self.altgr,
            58 => {
                if pressed {
                    self.caps = !self.caps;
                }
                return true;
            }
            _ => return false,
        };
        *slot = if pressed { slot.saturating_add(1) } else { slot.saturating_sub(1) };
        true
    }
}

impl Desktop {
    /// Connects to the compositor (WAYLAND_DISPLAY) and picks an output: by name, or the first.
    pub fn connect(output_name: Option<&str>) -> Result<Desktop, String> {
        let conn = Connection::connect_to_env().map_err(|e| format!("no Wayland desktop to share ({e})"))?;
        let (globals, mut queue) = registry_queue_init::<State>(&conn).map_err(|e| e.to_string())?;
        let qh = queue.handle();
        let mut state = State { outputs: vec![], frame: FrameState::default(), keymap: None };
        let shm: wl_shm::WlShm = globals.bind(&qh, 1..=1, ()).map_err(|_| "the compositor has no wl_shm")?;
        let screencopy: zwlr_screencopy_manager_v1::ZwlrScreencopyManagerV1 = globals.bind(&qh, 1..=3, ()).map_err(|_| {
            "the compositor cannot share its screen (no wlr-screencopy: Hyprland, sway and other wlroots compositors have it)"
        })?;
        let registry = globals.registry().clone();
        let mut seat: Option<wl_seat::WlSeat> = None;
        for g in globals.contents().clone_list() {
            if g.interface == "wl_output" {
                let idx = state.outputs.len();
                let out: wl_output::WlOutput = registry.bind(g.name, g.version.min(4), &qh, idx);
                state.outputs.push((out, OutputInfo::default()));
            } else if g.interface == "wl_seat" && seat.is_none() {
                seat = Some(registry.bind(g.name, g.version.min(7), &qh, ()));
            }
        }
        queue.roundtrip(&mut state).map_err(|e| e.to_string())?;
        queue.roundtrip(&mut state).map_err(|e| e.to_string())?;
        if state.outputs.is_empty() {
            return Err("the compositor has no outputs".into());
        }
        let output = match output_name {
            Some(n) => state
                .outputs
                .iter()
                .position(|(_, i)| i.name == n)
                .ok_or_else(|| format!("no output named {n} (there are: {})", Self::names(&state)))?,
            None => 0,
        };
        let mut desktop = Desktop {
            _conn: conn.clone(),
            conn,
            queue,
            qh,
            state,
            shm,
            screencopy,
            output,
            pointer: None,
            keyboard: None,
            buffer: None,
            pending: None,
            picture: None,
            mods: Modifiers::default(),
            start: std::time::Instant::now(),
        };
        if let Some(seat) = seat {
            desktop.input(&globals, &seat);
        }
        Ok(desktop)
    }

    fn names(state: &State) -> String {
        state.outputs.iter().map(|(_, i)| i.name.clone()).collect::<Vec<_>>().join(", ")
    }

    fn input(&mut self, globals: &wayland_client::globals::GlobalList, seat: &wl_seat::WlSeat) {
        let qh = &self.qh;
        if let Ok(m) = globals.bind::<zwlr_virtual_pointer_manager_v1::ZwlrVirtualPointerManagerV1, _, _>(qh, 1..=2, ()) {
            let out = &self.state.outputs[self.output].0;
            self.pointer = Some(if m.version() >= 2 {
                m.create_virtual_pointer_with_output(Some(seat), Some(out), qh, ())
            } else {
                m.create_virtual_pointer(Some(seat), qh, ())
            });
        }
        if let Ok(m) = globals.bind::<zwp_virtual_keyboard_manager_v1::ZwpVirtualKeyboardManagerV1, _, _>(qh, 1..=1, ()) {
            // The keyboard layout: the seat's own (a real keyboard's), else the system default from xkbcli.
            let _ = self.queue.roundtrip(&mut self.state);
            let keymap = self.state.keymap.clone().or_else(default_keymap);
            if let Some(text) = keymap {
                if let Some((fd, size)) = keymap_fd(&text) {
                    let kb = m.create_virtual_keyboard(seat, qh, ());
                    kb.keymap(1, fd.as_fd(), size);
                    self.keyboard = Some(kb);
                }
            }
        }
        let _ = self.conn.flush();
    }

    pub fn output(&self) -> OutputInfo {
        self.state.outputs[self.output].1.clone()
    }

    pub fn can_control(&self) -> (bool, bool) {
        (self.pointer.is_some(), self.keyboard.is_some())
    }

    fn time(&self) -> u32 {
        self.start.elapsed().as_millis() as u32
    }

    /// Asks for the next picture of the output. The compositor answers when it next draws the output (at once
    /// when something moves; not at all while the screen is still), so the answer is collected by `poll`.
    pub fn begin(&mut self) {
        if self.pending.is_some() {
            return;
        }
        self.state.frame = FrameState::default();
        let out = self.state.outputs[self.output].0.clone();
        self.pending = Some((self.screencopy.capture_output(1, &out, &self.qh, ()), false));
        let _ = self.conn.flush();
    }

    /// Reads the compositor's events for up to `wait`, and returns the picture once it is there.
    pub fn poll(&mut self, wait: std::time::Duration) -> Result<Option<Picture>, String> {
        let _ = self.conn.flush();
        self.queue.dispatch_pending(&mut self.state).map_err(|e| e.to_string())?;
        if !self.step()? {
            if let Some(guard) = self.queue.prepare_read() {
                let fd = guard.connection_fd();
                let mut fds = [PollFd::new(&fd, PollFlags::IN)];
                let ts = Timespec { tv_sec: wait.as_secs() as i64, tv_nsec: wait.subsec_nanos() as i64 };
                let ready = rustix::event::poll(&mut fds, Some(&ts)).unwrap_or(0) > 0;
                drop(fds);
                if ready {
                    let _ = guard.read();
                }
            }
            self.queue.dispatch_pending(&mut self.state).map_err(|e| e.to_string())?;
            self.step()?;
        }
        Ok(self.picture.take())
    }

    /// Moves the pending capture along; true when it finished (a picture, or a failure).
    fn step(&mut self) -> Result<bool, String> {
        let Some((frame, copying)) = self.pending.clone() else { return Ok(false) };
        let f = &self.state.frame;
        if f.failed {
            frame.destroy();
            self.pending = None;
            return Err("the compositor refused to share the screen".into());
        }
        if !copying {
            let v3 = self.screencopy.version() >= 3;
            if !(if v3 { f.buffer_done } else { f.format.is_some() }) {
                return Ok(false);
            }
            let (format, width, height, stride) = f.format.ok_or("no buffer format")?;
            let fmt = match format {
                WEnum::Value(f) => f,
                WEnum::Unknown(_) => return Err("an unknown pixel format".into()),
            };
            if !matches!(fmt, wl_shm::Format::Xrgb8888 | wl_shm::Format::Argb8888 | wl_shm::Format::Xbgr8888 | wl_shm::Format::Abgr8888) {
                return Err(format!("unsupported pixel format {fmt:?}"));
            }
            let key = (width, height, stride, fmt as u32);
            if self.buffer.as_ref().map(|b| b.key) != Some(key) {
                self.buffer = None;
                self.buffer = Some(self.make_buffer(fmt, width, height, stride)?);
            }
            frame.copy(&self.buffer.as_ref().unwrap().buffer);
            let _ = self.conn.flush();
            self.pending = Some((frame, true));
            return Ok(false);
        }
        if !f.ready {
            return Ok(false);
        }
        frame.destroy();
        self.pending = None;
        let buf = self.buffer.as_ref().unwrap();
        let (width, height, stride, fmt) = buf.key;
        let bgr = fmt == wl_shm::Format::Xrgb8888 as u32 || fmt == wl_shm::Format::Argb8888 as u32;
        let src = unsafe { std::slice::from_raw_parts(buf.ptr as *const u8, buf.len) };
        let row = (width * 4) as usize;
        let mut pixels = vec![0u8; row * height as usize];
        for y in 0..height as usize {
            let sy = if self.state.frame.y_invert { height as usize - 1 - y } else { y };
            let s = sy * stride as usize;
            pixels[y * row..(y + 1) * row].copy_from_slice(&src[s..s + row]);
        }
        self.picture = Some(Picture { width, height, bgr, pixels });
        Ok(true)
    }

    /// One picture, waiting for it (up to `timeout`): for tools and tests.
    pub fn capture(&mut self, timeout: std::time::Duration) -> Result<Option<Picture>, String> {
        self.begin();
        let end = std::time::Instant::now() + timeout;
        while std::time::Instant::now() < end {
            if let Some(p) = self.poll(std::time::Duration::from_millis(20))? {
                return Ok(Some(p));
            }
        }
        Ok(None)
    }

    fn make_buffer(&self, fmt: wl_shm::Format, width: u32, height: u32, stride: u32) -> Result<ShmBuffer, String> {
        let len = (stride * height) as usize;
        let fd = memfd_create(c"rdp-express", MemfdFlags::CLOEXEC).map_err(|e| e.to_string())?;
        ftruncate(&fd, len as u64).map_err(|e| e.to_string())?;
        let ptr = unsafe {
            mmap(std::ptr::null_mut(), len, ProtFlags::READ | ProtFlags::WRITE, MapFlags::SHARED, &fd, 0)
                .map_err(|e| e.to_string())?
        };
        let pool = self.shm.create_pool(fd.as_fd(), len as i32, &self.qh, ());
        let buffer = pool.create_buffer(0, width as i32, height as i32, stride as i32, fmt, &self.qh, ());
        Ok(ShmBuffer { buffer, pool, _fd: fd, ptr, len, key: (width, height, stride, fmt as u32) })
    }

    // ── input ──

    pub fn pointer_to(&mut self, x: u32, y: u32, width: u32, height: u32) {
        let t = self.time();
        if let Some(p) = &self.pointer {
            p.motion_absolute(t, x.min(width.saturating_sub(1)), y.min(height.saturating_sub(1)), width, height);
            p.frame();
            let _ = self.conn.flush();
        }
    }

    pub fn button(&mut self, button: u32, pressed: bool) {
        let t = self.time();
        if let Some(p) = &self.pointer {
            let state = if pressed { wl_pointer::ButtonState::Pressed } else { wl_pointer::ButtonState::Released };
            p.button(t, button, state);
            p.frame();
            let _ = self.conn.flush();
        }
    }

    /// Scrolling in steps (a wheel's notches): positive is down or right.
    pub fn scroll(&mut self, vertical: i32, horizontal: i32) {
        let t = self.time();
        if let Some(p) = &self.pointer {
            p.axis_source(wl_pointer::AxisSource::Wheel);
            for (axis, steps) in [(wl_pointer::Axis::VerticalScroll, vertical), (wl_pointer::Axis::HorizontalScroll, horizontal)] {
                if steps != 0 {
                    p.axis_discrete(t, axis, steps as f64 * 15.0, steps);
                }
            }
            p.frame();
            let _ = self.conn.flush();
        }
    }

    /// A key by its Linux (evdev) code.
    pub fn key(&mut self, code: u32, pressed: bool) {
        let t = self.time();
        if let Some(k) = &self.keyboard {
            k.key(t, code, if pressed { 1 } else { 0 });
            if self.mods.update(code, pressed) {
                k.modifiers(self.mods.depressed(), 0, if self.mods.caps { 2 } else { 0 }, 0);
            }
            let _ = self.conn.flush();
        }
    }

    /// Lets go of everything held (the viewer went away mid-press).
    pub fn release_all(&mut self) {
        let t = self.time();
        if let Some(k) = &self.keyboard {
            let held = [(42, self.mods.shift), (29, self.mods.ctrl), (56, self.mods.alt), (125, self.mods.logo), (100, self.mods.altgr)];
            for (code, count) in held {
                if count > 0 {
                    k.key(t, code, 0);
                }
            }
            k.modifiers(0, 0, if self.mods.caps { 2 } else { 0 }, 0);
        }
        self.mods = Modifiers { caps: self.mods.caps, ..Default::default() };
        if let Some(p) = &self.pointer {
            for b in [0x110, 0x111, 0x112] {
                p.button(t, b, wl_pointer::ButtonState::Released);
            }
            p.frame();
        }
        let _ = self.conn.flush();
    }
}

fn keymap_fd(text: &str) -> Option<(OwnedFd, u32)> {
    let mut bytes = text.as_bytes().to_vec();
    bytes.push(0);
    let fd = memfd_create(c"rdp-express-keymap", MemfdFlags::CLOEXEC).ok()?;
    rustix::io::write(&fd, &bytes).ok()?;
    Some((fd, bytes.len() as u32))
}

/// The system's default keyboard layout, compiled by xkbcommon's tool (when there is no real keyboard to copy).
fn default_keymap() -> Option<String> {
    for cmd in [vec!["xkbcli", "compile-keymap"], vec!["/usr/lib/xkbcommon/xkbcli-compile-keymap"]] {
        if let Ok(out) = std::process::Command::new(cmd[0]).args(&cmd[1..]).output() {
            if out.status.success() && !out.stdout.is_empty() {
                return String::from_utf8(out.stdout).ok();
            }
        }
    }
    None
}

impl Dispatch<wl_registry::WlRegistry, GlobalListContents> for State {
    fn event(_: &mut Self, _: &wl_registry::WlRegistry, _: wl_registry::Event, _: &GlobalListContents, _: &Connection, _: &QueueHandle<Self>) {}
}

impl Dispatch<wl_output::WlOutput, usize> for State {
    fn event(state: &mut Self, _: &wl_output::WlOutput, event: wl_output::Event, idx: &usize, _: &Connection, _: &QueueHandle<Self>) {
        let info = &mut state.outputs[*idx].1;
        match event {
            wl_output::Event::Mode { flags, width, height, .. } => {
                if let WEnum::Value(f) = flags {
                    if f.contains(wl_output::Mode::Current) {
                        info.width = width;
                        info.height = height;
                    }
                }
            }
            wl_output::Event::Name { name } => info.name = name,
            _ => {}
        }
    }
}

impl Dispatch<wl_seat::WlSeat, ()> for State {
    fn event(_: &mut Self, seat: &wl_seat::WlSeat, event: wl_seat::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        if let wl_seat::Event::Capabilities { capabilities: WEnum::Value(caps) } = event {
            if caps.contains(wl_seat::Capability::Keyboard) {
                seat.get_keyboard(qh, ());
            }
        }
    }
}

impl Dispatch<wl_keyboard::WlKeyboard, ()> for State {
    fn event(state: &mut Self, _: &wl_keyboard::WlKeyboard, event: wl_keyboard::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        if let wl_keyboard::Event::Keymap { format: WEnum::Value(wl_keyboard::KeymapFormat::XkbV1), fd, size } = event {
            let len = size as usize;
            if let Ok(ptr) = unsafe { mmap(std::ptr::null_mut(), len, ProtFlags::READ, MapFlags::PRIVATE, &fd, 0) } {
                let bytes = unsafe { std::slice::from_raw_parts(ptr as *const u8, len) };
                if let Ok(text) = CStr::from_bytes_until_nul(bytes).map(|c| c.to_string_lossy().into_owned()) {
                    state.keymap = Some(text);
                }
                unsafe {
                    let _ = munmap(ptr, len);
                }
            }
        }
    }
}

impl Dispatch<zwlr_screencopy_frame_v1::ZwlrScreencopyFrameV1, ()> for State {
    fn event(state: &mut Self, _: &zwlr_screencopy_frame_v1::ZwlrScreencopyFrameV1, event: zwlr_screencopy_frame_v1::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        use zwlr_screencopy_frame_v1::Event;
        match event {
            Event::Buffer { format, width, height, stride } => {
                // The first shm format offered; 8-bit RGB is what every compositor offers.
                if state.frame.format.is_none() {
                    state.frame.format = Some((format, width, height, stride));
                }
            }
            Event::Flags { flags } => {
                if let WEnum::Value(f) = flags {
                    state.frame.y_invert = f.contains(zwlr_screencopy_frame_v1::Flags::YInvert);
                }
            }
            Event::BufferDone => state.frame.buffer_done = true,
            Event::Ready { .. } => state.frame.ready = true,
            Event::Failed => state.frame.failed = true,
            _ => {}
        }
    }
}

delegate_noop!(State: ignore wl_shm::WlShm);
delegate_noop!(State: wl_shm_pool::WlShmPool);
delegate_noop!(State: ignore wl_buffer::WlBuffer);
delegate_noop!(State: zwlr_screencopy_manager_v1::ZwlrScreencopyManagerV1);
delegate_noop!(State: zwlr_virtual_pointer_manager_v1::ZwlrVirtualPointerManagerV1);
delegate_noop!(State: zwlr_virtual_pointer_v1::ZwlrVirtualPointerV1);
delegate_noop!(State: zwp_virtual_keyboard_manager_v1::ZwpVirtualKeyboardManagerV1);
delegate_noop!(State: zwp_virtual_keyboard_v1::ZwpVirtualKeyboardV1);
