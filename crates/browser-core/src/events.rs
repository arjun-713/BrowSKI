//! Session-level browser events.
//!
//! [`BrowserEvent`] is the agent-facing projection of [`CdpEvent`]: protocol
//! details (session ids, loader ids, raw payloads) are resolved against the
//! [`TabRegistry`](crate::model::TabRegistry) into tab-scoped facts. The
//! translation lives in the session event pump; this module owns the enum.

use browser_agent_cdp::{FrameId, TabId};
use serde::{Deserialize, Serialize};

/// Agent-facing browser lifecycle events.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum BrowserEvent {
    NavigationStarted {
        tab: TabId,
        url: String,
    },
    NavigationCompleted {
        tab: TabId,
        url: String,
    },
    FrameAttached {
        tab: TabId,
        frame: FrameId,
    },
    FrameDetached {
        tab: TabId,
        frame: FrameId,
    },
    TargetCreated {
        tab: TabId,
    },
    TargetDestroyed {
        tab: TabId,
    },
    DialogOpened {
        tab: TabId,
        dialog_type: String,
        message: String,
    },
    DownloadStarted {
        tab: TabId,
        filename: String,
        url: String,
    },
    DownloadCompleted {
        tab: TabId,
        filename: String,
    },
    PageCrashed {
        tab: TabId,
    },
    ConnectionLost,
}

impl BrowserEvent {
    /// Short label for dispatch-latency metrics.
    pub fn kind(&self) -> &'static str {
        match self {
            BrowserEvent::NavigationStarted { .. } => "navigation_started",
            BrowserEvent::NavigationCompleted { .. } => "navigation_completed",
            BrowserEvent::FrameAttached { .. } => "frame_attached",
            BrowserEvent::FrameDetached { .. } => "frame_detached",
            BrowserEvent::TargetCreated { .. } => "target_created",
            BrowserEvent::TargetDestroyed { .. } => "target_destroyed",
            BrowserEvent::DialogOpened { .. } => "dialog_opened",
            BrowserEvent::DownloadStarted { .. } => "download_started",
            BrowserEvent::DownloadCompleted { .. } => "download_completed",
            BrowserEvent::PageCrashed { .. } => "page_crashed",
            BrowserEvent::ConnectionLost => "connection_lost",
        }
    }
}
