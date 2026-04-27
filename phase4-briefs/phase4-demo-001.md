---
ac_count: 5
blocks: []
complexity: S
context: demo
depends_on:
- phase4-evals-001
- phase4-polish-001
estimated_hours: 4
id: phase4-demo-001
phase: 4
sdd_mode: lightweight
state: ready
title: Landing copy + demo script + screen recording outline
touches_adrs: []
---

# Brief: phase4-demo-001 — Landing copy + demo script + screen recording outline


## Context

This is the closing brief for the entire VaultChain V1 build. After three phases of architecture and four phases of feature work, the project ships with no marketing surface — a brilliant codebase that nobody can quickly evaluate. This brief delivers three artefacts whose job is to take a curious recruiter or engineering reviewer from `0` to `compelling` in under five minutes:

1. **A public landing page** at the root of the deployed site (`/`) — single-page, marketing-shaped, replacing the current "redirect to /login" behaviour for unauthenticated visitors. Hero + feature grid + architecture diagram + technology callouts + CTA to GitHub repo + CTA to demo recording.

2. **A 90-second demo screen recording** showing the AI-assisted withdrawal flow end-to-end: open chat, ask the assistant to send tokens, prep card appears, confirm with TOTP, watch broadcasting → confirmed. The recording is the deliverable a reviewer who skips reading code will watch first.

3. **A `README.md` overhaul at the repo root** — opens with three lines that hook (project tagline, primary tech stack badges, link to demo), then has a structured walkthrough of the architecture for engineering readers. The current README likely is engineering-only (or empty); this brief makes it dual-audience: a non-engineer recruiter sees the demo and tagline, an engineer reviewer scrolls down for technical depth.

**The framing:** this is a **portfolio project** built to demonstrate production-grade engineering practice on a hard domain (multi-chain custody + AI-assisted UX). The demo and landing should foreground that — not as commercial positioning, but as honest "look at the depth of the work" framing. A recruiter watching the demo should think "this person knows how to ship something serious"; an engineer reading the README should think "this person made informed architectural decisions."

**What does NOT ship:**
- A blog post or article. (Out of scope; the README + landing are the long-form.)
- Email/contact collection or a newsletter signup. (Pure portfolio, no funnel.)
- SEO meta-tags / OG-image optimization. (Out of scope; landing has basic semantic HTML, not a full SEO push.)
- Animations or video on the landing page. (Static + the embedded recording is enough.)
- A demo video voiceover. (Captions / annotations sufficient; voice adds production cost without proportional value.)
- Multi-language landing or README. (English only; consistent with V1 product UI.)

---

## Architecture pointers

- **Layer:** frontend SPA (landing page lives in `web/`) + repo-root documentation.
- **Packages touched:**
  - `web/src/pages/Landing.tsx` (new)
  - `web/src/components/landing/HeroSection.tsx`, `FeatureGrid.tsx`, `ArchitectureDiagram.tsx`, `TechCallouts.tsx`, `CtaSection.tsx` (new)
  - `web/src/App.tsx` (route `/` for unauthenticated → `<Landing />`; authenticated → existing dashboard redirect)
  - `web/public/demo.mp4` (the 90-second recording — committed binary, ~5–15 MB)
  - `web/public/demo-poster.png` (poster image shown before video plays)
  - `web/public/architecture-diagram.svg` (rendered diagram — generated once, committed; mirrors the Mermaid in `architecture-decisions.md`)
  - `README.md` (repo root — major overhaul)
  - `docs/demo-script.md` (the script behind the recording — committed for reference, used by future re-recordings)
- **API consumed:** none.
- **OpenAPI surface change:** no.

---

## Acceptance Criteria

- **AC-phase4-demo-001-01:** Given the landing page route `/` for unauthenticated visitors, when navigated, then it renders a single-page layout: hero (8vh from top, centered) with project name "VaultChain", tagline `"A custodial multi-chain wallet with an AI assistant — Ethereum, Tron, Solana — built to demonstrate production-grade engineering practice."`, and two CTAs ("View on GitHub" → repo link, "Watch demo" → scrolls to recording or opens in modal). Below the hero: a 3-column feature grid (each column: icon + 2-line headline + 3–4 sentence sub-copy) — features: "Multi-chain custody", "AI assistant with prep-card safety boundary", "Production-grade DDD + TDD architecture". Below the grid: an architecture-diagram section with the SVG embedded + a one-paragraph caption. Below: a "Technology" section listing key choices (FastAPI, PostgreSQL + pgvector, React + TanStack Query, Anthropic Claude + Google Gemini embeddings) with a short justification per choice. Below: the embedded demo video (90 seconds, autoplay false, controls true, poster). Footer: links to GitHub, license (MIT or similar), and a humble "Built by [name] as a portfolio project" line.

- **AC-phase4-demo-001-02:** Given the landing page is responsive, when viewed at 320px / 768px / 1440px, then: at 320px, all sections stack vertically (feature grid becomes single column; architecture diagram scales to fit width with horizontal scroll if needed but doesn't overflow); at 768px, feature grid is 2-column; at 1440px, 3-column with comfortable whitespace. Hero remains readable at all widths; tagline does not break mid-word. Tested via the same `responsive-smoke.spec.ts` extended in `phase4-polish-001` AC-10.

- **AC-phase4-demo-001-03:** Given the architecture diagram SVG, when rendered, then it shows the seven bounded contexts (Identity, Custody, Chains, Ledger, Transactions, KYC, AI) as labelled boxes with arrows showing primary dependencies (e.g., AI ──prepare──▶ Transactions ──executes──▶ Custody). Visually distinguishes the four AI sub-domains (Chat, Tools, Suggestions, Memory). Annotates the "AI never imports Custody" import-linter contract as a labelled forbidden arrow (red dashed). The SVG is hand-crafted (or generated once from a Mermaid source committed in `docs/diagrams/architecture.mmd`) — clean, professional, not a screenshot. ~600px wide canvas, scales via SVG viewBox.

- **AC-phase4-demo-001-04:** Given the 90-second demo recording `web/public/demo.mp4`, when played, then it shows: (0–5s) login screen + magic link, abbreviated; (5–15s) dashboard with portfolio + suggestions strip visible; (15–25s) click chat button → panel opens → user types "send 0.05 ETH to 0xabc..."; (25–60s) assistant streams response → tool-running pills → prep card appears with preview; (60–80s) click Confirm → TOTP modal → enter code → prep card morphs to Submitted; (80–90s) view transaction detail → broadcasting → confirmed. Captions / on-screen text annotations highlight what's happening at each beat (no voiceover; the captions carry the explanation). Resolution: 1280×720 minimum; 1920×1080 preferred; H.264 encode; under 15MB. **Frame-rate steady, no dropped frames; cursor visible and deliberate (not jittery)**.

- **AC-phase4-demo-001-05:** Given the README.md at repo root, when opened on GitHub, then the first 30 lines (the "above-the-fold" view) contain: a hero-style header (project name + one-line tagline); badges (build status, license, optionally a "made with" badge); a 3–4 sentence "What is this?" paragraph; a clickable link to the live demo video (raw URL or embedded `<img src="poster.png" alt="Watch demo">`); the GitHub-rendered demo poster image. Below the fold (scrollable): "Architecture overview" with the SVG embedded, "Quick start" with `docker compose up` instructions, "Technology choices" section linking to the relevant ADRs, "Phase-by-phase breakdown" listing the four phases with brief summaries (4 phases × ~3 sentences each), "Test strategy" section linking to ADR-006, "License" footer. The README is the single longest engineering doc in the repo intentionally — it's the engineering reviewer's home base.

- **AC-phase4-demo-001-06:** Given the demo script at `docs/demo-script.md`, when reviewed, then it documents: the exact sequence of clicks/keystrokes; the test user's seed state required to make the recording reproducible (which user, which balances, which conversation history); the OBS / screen-recorder settings used (resolution, frame rate, audio off); the captions/annotations text per timestamp; how to re-record if the UI changes. The script is short — 1–2 pages — but precise enough that another developer (or future-you) could re-record without guessing.

- **AC-phase4-demo-001-07:** Given the landing page's "Technology" section, when rendered, then it covers six callouts in a clear grid: (1) **FastAPI + Python 3.13** — "async-native backend chosen for IO-heavy chain RPC and AI streaming"; (2) **PostgreSQL + pgvector** — "single primary database with schema-per-context boundaries; pgvector for embeddings"; (3) **React + TanStack Query** — "frontend with declarative server-state management; SSE-driven cache invalidation"; (4) **Anthropic Claude (Sonnet + Haiku)** — "Sonnet for chat, Haiku for transaction summaries — cost-conscious model selection"; (5) **Google Gemini embeddings** — "768-dim Matryoshka-truncated `gemini-embedding-001` for retrieval; multilingual quality at 75% storage saving — see ADR-010"; (6) **DDD + TDD** — "clean bounded contexts, test pyramid with property tests at safety-critical boundaries — see ADR-006". Each callout links to the relevant ADR (e.g., ADR-010 for embeddings) and to the relevant repo path. The links are subtle, not loud — engineering readers explore them; recruiters see the high-level callouts.

- **AC-phase4-demo-001-08:** Given the recording's caption / annotation overlay, when shown, then key moments have brief on-screen text: at 18s "User asks the assistant in natural language", at 35s "Assistant calls the `prepare_send_transaction` tool — never the executor directly", at 48s "Prep card shows the preview before any signing happens", at 70s "TOTP confirms — assistant cannot bypass this step". The on-screen text is subtitle-style (bottom of frame, max 2 lines, fades in/out). Rendered via post-production tool (DaVinci Resolve, Final Cut, or even ffmpeg subtitle burn-in) — the script in AC-06 specifies the timestamps + text; production tool choice is implementor's preference.

- **AC-phase4-demo-001-09:** Given the landing page's accessibility, when audited via axe-playwright, then it has zero serious/critical violations. Specific concerns: hero has proper heading hierarchy (h1 once); CTAs have descriptive labels (not "click here"); the embedded video has a `<track>` element with English captions (the same caption text from the recording's overlay — bundled as a `.vtt` file). The architecture diagram has descriptive `<title>` and `<desc>` elements within the SVG for screen-reader narration ("Architecture diagram showing seven bounded contexts: Identity, Custody, Chains, Ledger, Transactions, KYC, and AI"). Tested via the same Playwright accessibility-audit extended in `phase4-polish-001` AC-11.

- **AC-phase4-demo-001-10:** Given the deployed landing page is reachable at the production URL's root, when a fresh (unauthenticated) browser visits, then the page loads in <2 seconds on a typical broadband connection. Performance: the SVG is <50KB, the demo MP4 is lazy-loaded (poster shown until user clicks play, then `<video preload="none">` fetches), the JavaScript bundle for the landing route is code-split from the main app (TanStack Router or similar split). The landing has no third-party analytics, no tracking pixels, no external font CDN — first-party assets only.

---

## Out of Scope

- A blog post or written article.
- Email collection / newsletter signup.
- Full SEO push (OG images, schema.org markup, sitemap).
- Voiceover on the demo recording.
- Multi-language landing or README.
- Animations on landing page.
- Subdomain routing (e.g., marketing on `vaultchain.dev`, app on `app.vaultchain.dev`) — V2.
- A `/docs` site separate from the README — V2.
- A "Sign up for early access" CTA — explicit non-goal; this is a portfolio, not a product launch.
- Partner / integration logos. None apply.

---

## Dependencies

- **Code dependencies:** all prior Phase 4 briefs shipped to staging or production (the recording requires a working AI flow); `phase4-polish-001` shipped (the recording shows polished UI).
- **Data dependencies:** a seeded test user account on the deployed environment to record the demo against; same shape as `phase4-evals-001`'s seeds.
- **External dependencies:** screen-recording software (OBS Studio is recommended free option; QuickTime on macOS works for basic captures); video editor for caption overlay (DaVinci Resolve free tier or ffmpeg with subtitle burn-in); SVG editor or hand-coding for the architecture diagram.

---

## Test Coverage Required

- [ ] **Component tests:** `Landing.test.tsx`, `HeroSection.test.tsx`, `FeatureGrid.test.tsx`, `ArchitectureDiagram.test.tsx`, `TechCallouts.test.tsx`, `CtaSection.test.tsx` — render correctly with default props, links navigate to expected URLs, semantic HTML structure correct.
- [ ] **Playwright responsive:** the existing `responsive-smoke.spec.ts` from `phase4-polish-001` extended to include the landing page at all 6 viewports. Covers AC-02.
- [ ] **Playwright accessibility:** the existing accessibility audit extended to cover the landing page; zero serious/critical. Covers AC-09.
- [ ] **README link-check:** a CI script (or pre-commit hook) verifies all relative links in `README.md` resolve to existing files. Trivial to implement; catches the common "renamed an ADR file" regression.
- [ ] **Performance smoke (manual):** lighthouse run against the deployed landing page targeting Performance ≥80, Accessibility ≥95. Documented in PR but not blocking — third-party tooling output, hard to gate.

---

## Done Definition

- [ ] All ACs verified by named test cases (AC ↔ test mapping in PR description).
- [ ] All listed test categories implemented and passing locally.
- [ ] Landing page deployed and reachable at production root URL.
- [ ] `web/public/demo.mp4`, `demo-poster.png`, `demo-captions.vtt`, `architecture-diagram.svg` all committed.
- [ ] `README.md` overhauled and reviewed by a second pair of eyes (or self-review after 24h cooldown — the README's tone matters).
- [ ] `docs/demo-script.md` committed.
- [ ] `docs/diagrams/architecture.mmd` (Mermaid source for the SVG) committed for future regeneration.
- [ ] `tsc --noEmit --strict` clean.
- [ ] `eslint` + `prettier` clean.
- [ ] Single PR. Conventional commit: `feat(landing): public marketing surface + demo recording + README [phase4-demo-001]`.
- [ ] PR description: a screenshot of the landing page above the fold + a thumbnail link to the recording. The PR is the deliverable's preview.

---

## Implementation Notes

- **The README's first 30 lines matter most.** GitHub renders them in the repo's homepage above the fold; recruiters and engineers form their first impression there. Iterate on this section more than any other; ship a 2nd draft after a 24h cooldown re-read.
- **The demo recording is the highest-value artefact** — a single mediocre recording undoes the polish pass. Re-record until the cursor is deliberate, no fumbling, no error states sneaking in. Budget time for 3–5 takes.
- **Tagline iteration.** The first proposed tagline ("A custodial multi-chain wallet with an AI assistant — built to demonstrate production-grade engineering practice") is functional but not catchy. Try variants in the PR description and commit the best. Avoid cliches ("Cutting-edge", "Revolutionary", "Powered by AI").
- **Architecture diagram aesthetics matter.** A rough Mermaid render screenshotted into PNG signals "didn't care"; a clean SVG with intentional layout signals "shipped with discipline." If hand-authoring the SVG is too costly, use Excalidraw → export SVG, then clean up the result.
- **The video's resolution and frame rate matter for portfolio impression.** 1080p60 looks sharp on modern displays; 720p30 looks cheap. Recording at 1920×1080 at 60 fps then encoding to 1280×720 at 30 fps for the committed file is a reasonable middle ground (smaller file size while source quality is preserved if re-encoding for any reason).
- **Captions in the video** should match the captions in the `<track>` element — single source of truth (the script in AC-06 keeps them aligned).
- **Don't over-design the landing.** It's a single page. Use the existing design tokens from the app (same colors, same fonts) so it feels like the same product. Resist trendy gradients / glassmorphism if they'd clash with the app's UI tone.
- **The "Built by [name]" footer** is a personal call. If the developer wants attribution, use it; if anonymity is preferred, omit. The repository's CODEOWNERS or license header handles attribution mechanically.
- **Lighthouse Performance score >80** is achievable on a static landing with a lazy-loaded video. If the score is dropping due to the embedded video or the SVG, debug; the polish discipline carries over to landing as well.

---

## Risk / Friction

- **Recording quality is variable.** A single ugly frame (mouse over a wrong element, a hesitation, a typo in the message) ruins the impression. Plan for 3–5 takes; commit the best one. If perfectionism stalls progress, ship "good enough" — a slightly imperfect 90-second video beats a never-shipped polished one.
- **The demo recording bakes-in the current UI.** Any post-recording UI change makes the video feel stale. The recording should be re-recorded annually or on major UI changes (the script in AC-06 makes this cheap, ~30 minutes per re-record).
- **README tone is hard to nail.** Too humble: undersells the work. Too confident: rings hollow. Aim for "specific and factual" — concrete details about the architecture decisions made + the learnings, less "best-in-class" language. The 24h cooldown re-read catches over-claiming.
- **The architecture diagram inevitably oversimplifies.** Seven contexts × dozens of internal modules × hundreds of decisions cannot fit in a 600-pixel SVG. The diagram's job is to invite, not to document — a reader who's interested then reads the architecture-decisions doc. Document the simplification deliberately in the SVG caption ("Simplified for overview; see `docs/architecture-decisions.md` for the full picture").
- **Reviewer asking "why is this a portfolio project, not a real product?"** — honest framing in the README. The depth of the architecture, the test discipline, the eval harness — these are the production-grade signal. The "portfolio" framing is honest about scope (no real users, no liability surface) without diminishing the engineering quality.
- **The `<video>` element on iOS Safari** has quirks — autoplay restrictions, custom controls. Use the browser-default `controls` attribute (no custom controls), `preload="none"` to avoid quota burn, and the poster image to give a deliberate first frame. Test on a real iOS device before merging.
- **The PR is unusual** — it's mostly content, not code. A traditional code-review approach (per-line) doesn't fit. The reviewer should focus on: does the landing communicate? Does the demo demonstrate? Does the README make me want to read further? If yes, ship.
