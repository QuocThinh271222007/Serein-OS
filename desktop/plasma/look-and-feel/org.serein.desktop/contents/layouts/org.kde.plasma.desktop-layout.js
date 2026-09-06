// Serein default panel layout.
//
// Applied by Plasma's Look-and-Feel package loader to a session with no
// existing layout of its own (first login) — see
// docs/desktop/configuration-ownership.md. Never touches a session that
// already has a layout, so an existing user is never affected.
//
// Deliberately minimal, per docs/desktop/architecture.md's panel target:
// one bottom panel with an application launcher, a task manager, a
// system tray, and a clock. No desktop widgets, no extra applets.

var panel = new Panel;
panel.location = "bottom";
panel.height = gridUnit * 2.1;

panel.addWidget("org.kde.plasma.kickoff");
panel.addWidget("org.kde.plasma.icontasks");
panel.addWidget("org.kde.plasma.marginsseparator");
panel.addWidget("org.kde.plasma.systemtray");
panel.addWidget("org.kde.plasma.digitalclock");
