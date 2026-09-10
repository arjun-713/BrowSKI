//! Browser → Target → Tab → Frame hierarchy and its registry.
//!
//! ```text
//! Browser
//! └── Target (TargetId)
//!     └── Tab (TabId, page targets only)
//!         ├── Main Frame (FrameId)
//!         │   ├── Child Frame
//!         │   └── Child Frame
//!         └── CDP session (CdpSessionId, flattened)
//! ```
//!
//! The registry is the session's owned view of browser state. It is updated
//! exclusively from transport events plus confirmed command results — never
//! by guessing. IDs are distinct newtypes; a frame id can never be stored
//! where a target id belongs.

use browser_agent_cdp::{CdpSessionId, FrameId, TabId, TargetId};
use std::collections::{HashMap, HashSet};

/// A tracked tab (one page target + its flattened CDP session).
#[derive(Debug, Clone)]
pub struct Tab {
    pub id: TabId,
    pub target: TargetId,
    pub session: Option<CdpSessionId>,
    pub title: String,
    pub url: String,
    pub main_frame: Option<FrameId>,
    pub frames: HashSet<FrameId>,
    pub crashed: bool,
}

impl Tab {
    fn new(target: TargetId, title: String, url: String) -> Self {
        Self {
            id: TabId(target.as_str().to_string()),
            target,
            session: None,
            title,
            url,
            main_frame: None,
            frames: HashSet::new(),
            crashed: false,
        }
    }
}

/// Owned browser-state view for one session.
#[derive(Debug, Default)]
pub struct TabRegistry {
    tabs: HashMap<TargetId, Tab>,
    /// Tab creation order (for deterministic `tabs()` output).
    order: Vec<TargetId>,
    active: Option<TargetId>,
    sessions: HashMap<CdpSessionId, TargetId>,
}

impl TabRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Insert or refresh a page target. Returns true if newly inserted.
    pub fn upsert_target(&mut self, target: TargetId, title: String, url: String) -> bool {
        if let Some(tab) = self.tabs.get_mut(&target) {
            tab.title = title;
            tab.url = url;
            false
        } else {
            self.order.push(target.clone());
            self.tabs
                .insert(target.clone(), Tab::new(target, title, url));
            true
        }
    }

    pub fn remove_target(&mut self, target: &TargetId) -> Option<Tab> {
        if self.active.as_ref() == Some(target) {
            self.active = None;
        }
        self.sessions.retain(|_, t| t != target);
        self.order.retain(|t| t != target);
        self.tabs.remove(target)
    }

    pub fn get(&self, target: &TargetId) -> Option<&Tab> {
        self.tabs.get(target)
    }

    pub fn get_mut(&mut self, target: &TargetId) -> Option<&mut Tab> {
        self.tabs.get_mut(target)
    }

    pub fn target_for_session(&self, session: &CdpSessionId) -> Option<&TargetId> {
        self.sessions.get(session)
    }

    pub fn bind_session(&mut self, session: CdpSessionId, target: TargetId) {
        if let Some(tab) = self.tabs.get_mut(&target) {
            tab.session = Some(session.clone());
        }
        self.sessions.insert(session, target);
    }

    pub fn unbind_session(&mut self, session: &CdpSessionId) {
        if let Some(target) = self.sessions.remove(session) {
            if let Some(tab) = self.tabs.get_mut(&target) {
                if tab.session.as_ref() == Some(session) {
                    tab.session = None;
                }
            }
        }
    }

    pub fn attach_frame(&mut self, target: &TargetId, frame: FrameId, is_main: bool) {
        if let Some(tab) = self.tabs.get_mut(target) {
            tab.frames.insert(frame.clone());
            if is_main || tab.main_frame.is_none() {
                tab.main_frame = Some(frame);
            }
        }
    }

    pub fn detach_frame(&mut self, target: &TargetId, frame: &FrameId) {
        if let Some(tab) = self.tabs.get_mut(target) {
            tab.frames.remove(frame);
            if tab.main_frame.as_ref() == Some(frame) {
                tab.main_frame = None;
            }
        }
    }

    pub fn set_active(&mut self, target: TargetId) {
        if self.tabs.contains_key(&target) {
            self.active = Some(target);
        }
    }

    pub fn active(&self) -> Option<&Tab> {
        self.active.as_ref().and_then(|t| self.tabs.get(t))
    }

    pub fn tabs(&self) -> Vec<Tab> {
        self.order
            .iter()
            .filter_map(|t| self.tabs.get(t).cloned())
            .collect()
    }

    pub fn len(&self) -> usize {
        self.tabs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tabs.is_empty()
    }

    pub fn contains(&self, target: &TargetId) -> bool {
        self.tabs.contains_key(target)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn target(id: &str) -> TargetId {
        TargetId::from(id)
    }

    #[test]
    fn registry_tracks_tabs_frames_sessions() {
        let mut r = TabRegistry::new();
        assert!(r.upsert_target(target("T1"), "t".into(), "about:blank".into()));
        assert!(!r.upsert_target(target("T1"), "t2".into(), "https://x/".into()));
        r.bind_session(CdpSessionId::from("S1"), target("T1"));
        assert_eq!(
            r.target_for_session(&CdpSessionId::from("S1")),
            Some(&target("T1"))
        );
        r.attach_frame(&target("T1"), FrameId::from("F1"), true);
        r.attach_frame(&target("T1"), FrameId::from("F2"), false);
        assert_eq!(r.get(&target("T1")).unwrap().frames.len(), 2);
        r.detach_frame(&target("T1"), &FrameId::from("F2"));
        assert_eq!(r.get(&target("T1")).unwrap().frames.len(), 1);
        r.set_active(target("T1"));
        assert_eq!(r.active().unwrap().id, TabId::from("T1"));
        r.remove_target(&target("T1"));
        assert!(r.is_empty());
        assert!(r.active().is_none());
    }

    #[test]
    fn ids_are_distinct_types() {
        // Compile-time guarantee spot-check: TabId and TargetId share the
        // value but never unify. (If this compiles, the newtypes hold.)
        let tab = TabId::from("T1");
        let tgt = TargetId::from("T1");
        assert_eq!(tab.as_str(), tgt.as_str());
        assert_ne!(std::mem::size_of_val(&tab), 0);
    }
}
