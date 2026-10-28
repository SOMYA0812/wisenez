# Wisnez visual system

## Current direction

The frontend adapts architectural photography, warm neutrals, rounded image frames, light sans-serif typography, and capsule navigation from Eloqwnt's Siwa Capital project to an operational AI app.

User reference: [We Create Corporate Websites](https://dribbble.com/shots/27154885-We-Create-Corporate-Websites). Dribbble's interactive page required human verification. The project's public indexed artwork supplied visual grounding: [Siwa Capital artwork](https://cdn.dribbble.com/userupload/46881549/file/f9e1c4e8608bc8a7944616cba0406bf1.png?resize=1440x1080&vertical=center).

Active app concept: `dealdesk-warm-concept.png`.

### Tokens and layout

- Canvas: warm cream `#f5ede1`; panels: warm white `#fffdfa`; command panel: sand `#eee3d3`.
- Text: charcoal brown `#241c16`; secondary: `#786b5e`; borders: `#e5dccf`.
- Primary action: dark brown `#38291d`; hover: `#5a4933`; focus: `#895e3b`.
- Hero: generated sunset architecture photo, 22px radius, native white heading and subtitle. No text or controls are baked into the photo.
- Typography: Arial/Helvetica sans-serif; 50px light desktop hero title, 24px section headings, 40px mobile hero title.
- Layout: roughly 60px desktop gutters; photo header; centred 570px capsule tabs; 1.65:1 workspace columns; shared policy table below.
- Settings sidebar: initially collapsed, with an accessible native expansion control for providers and saved workflow selection.
- Mobile: stacked columns, full-width tabs, independently scrolling tables, hidden secondary hero note, and accessible settings. Selected lead tags wrap rather than disappearing.
- Review, Execution, Impact use the same warm surfaces, dark buttons, rounded disclosures and explicit status messages.

### Assets and implementation

`static/dealdesk-architecture.png` is an original production image generated with built-in Image Gen from the selected concept. It is a panoramic photorealistic cityscape with a curved dark-glass tower at left, rectangular glass tower at right, sunset reflections and natural dark lower regions; no text, logos, UI or artificial overlay. It is intentionally in the reference's visual direction rather than a reused Siwa business asset.

Streamlit serves it through `/app/static/dealdesk-architecture.png`. Keep static serving enabled in `.streamlit/config.toml`. Styling and the hero component live in `dealdesk/theme.py`; workflow UI remains in `dealdesk/ui.py`. Model, approval and execution policies were not changed by the restyle.

## Historical first design

The following describes the earlier interface, retained for reference only. It is superseded by the warm design above.

Concept: `dealdesk-concept.png`, generated with the built-in Image Gen tool from the approved functional plan. This is a design reference, not a runtime app asset.

- Main background: true white `#ffffff`; sidebar: pale gray `#f1f5f8`.
- Text: navy `#152a3b`; secondary text: slate `#697582`; border: `#dfe6ed`.
- Primary action: emerald `#087f63`; white button text; native visible focus indicators.
- Typography: system sans-serif, 38px desktop title, 26px section headings, readable 14–16px controls/body text. Mobile title scales down.
- Layout: quiet left sidebar; workspace and brief in 1.6:1 columns; four horizontal native tabs; table-led content; shared policy rows below. Mobile stacks columns.
- Components: native Streamlit tables, forms, buttons, tabs, disclosures and text fields. No decorative dashboard charts or fake operational metrics.
- Primary copy: Wisnez; Your AI team. Your final say.; Your next move, ready for review.; Turn new enquiries into thoughtful follow-ups. Approve every change before it happens.; Workspace; Review; Execution; Impact; Lead workspace; Give your team a brief; Prepare workflow; How your team works; Business memory.
- Functional extensions to the concept: explicit agent-mode labels, workflow history, lead multiselect, source editing/fresh-enquiry forms, approval controls and failure-injection controls. These implement requirements from the plan.
- Contact fixtures use reserved `.example` domains instead of the concept's illustrative addresses.

Review extends the same shell with exact CRM diffs and complete drafts; Execution uses open event rows and an outbox; Impact shows four operational metrics with the estimate assumption.

The concept prompt is preserved in the generation tool call in the project chat. Runtime text and controls are all implemented in code; no raster mockup is used as interface content.
