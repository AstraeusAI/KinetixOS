pragma Singleton
import QtQuick
import Quickshell.Services.Notifications

// Single shared NotificationServer instance for the session.
// NOTE (Plasma): plasmashell owns org.freedesktop.Notifications, so this
// server sits in "retry" and tracked stays empty — the toast overlay is inert
// here but harmless (zero-size input region when empty). It activates on
// compositors without their own notification daemon.
QtObject {
    // NOTE: NotificationServer must live in a *property* here, not as a
    // child object — QtObject has no default property for children, so a
    // nested `NotificationServer { id: ... }` fails to load. Aliases must
    // likewise point at an id, which a property value has none of, so
    // `tracked` stays a plain binding to the (identity-stable) live model:
    // the Repeater stays connected to the model object itself.
    property NotificationServer server: NotificationServer {
        keepOnReload: true
        actionsSupported: true
        bodySupported: true
        bodyMarkupSupported: true
        bodyHyperlinksSupported: true
        imageSupported: true
        persistenceSupported: true
        inlineReplySupported: true
        // Without this, every notification is discarded the moment the
        // signal handler returns — the #1 "notifications just vanish" bug.
        onNotification: function(n) { n.tracked = true; }
    }
    property var tracked: server ? server.trackedNotifications : []
}
