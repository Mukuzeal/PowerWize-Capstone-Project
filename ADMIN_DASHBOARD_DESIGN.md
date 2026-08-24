# Admin Dashboard Redesign
**Light Mode + Apple Design Language**

**Status:** Design Phase  
**Last Updated:** 2026-08-21  
**Owner:** Jan McZeal Bandao

---

## 1. Overview

Redesign the PowerWize admin dashboard to:
- Support **light mode** (replacing static dark green theme)
- Apply **Apple Design principles** (fluidity, interruptibility, spatial consistency, momentum)
- Implement **engaging animations** using animation vocabulary (stagger, scale-in, spring physics)
- Ensure **accessibility compliance** (reduced motion, color contrast, keyboard navigation)

### Current State
- Dark green theme only (`--green-dk: #0D3B27`)
- Fixed 56px topbar + 230px sidebar
- Static CSS transitions (no physics-based motion)
- No theme toggle or persistence

### Design Goals
1. **Dual-mode theming** with localStorage persistence
2. **Fluid interactions** that respond instantly and can be interrupted mid-animation
3. **Material design surfaces** with translucency and depth
4. **Momentum-aware animations** that carry velocity from gestures
5. **Spatial consistency** (enter/exit along same path, origin-aware animation)

---

## 2. Design Decisions

### 2.1 Theming Architecture

**Implementation:**
- CSS custom properties (`:root`) adapt to `prefers-color-scheme: light | dark`
- Theme toggle button in topbar (sun/moon icon)
- Preference stored in `localStorage` with key `powerwize-theme`
- Automatic fallback to system preference if no saved preference

**Color Token Strategy:**
Replace 14 hardcoded colors with semantic CSS variables:
```css
:root {
  /* Light mode base */
  --bg-primary: #F8F9FA;
  --bg-secondary: #FFFFFF;
  --text-primary: #0F1419;
  --text-secondary: #4B5563;
  --border-color: #E8EEF2;
  
  /* Light mode theme colors */
  --accent-green: #0D6E47;
  --accent-gold: #D4A72A;
  --status-success: #20C997;
  --status-warning: #FFC107;
  --status-error: #DC3545;
}

@media (prefers-color-scheme: dark) {
  :root {
    /* Dark mode base */
    --bg-primary: #0F1419;
    --bg-secondary: #1A2332;
    --text-primary: #E8EEF2;
    --text-secondary: #B0B8C4;
    --border-color: #2D3E52;
    
    /* Dark mode theme colors */
    --accent-green: #20C997;
    --accent-gold: #D4A72A;
    --status-success: #51CF66;
    --status-warning: #FFD43B;
    --status-error: #FF8787;
  }
}
```

---

## 2.2 Light Mode Palette

| Component | Light | Purpose |
|-----------|-------|---------|
| Background | `#F8F9FA` | Warm neutral, reduces eye strain |
| Sidebar/Topbar | `#FFFFFF` | Clean separation, accessible contrast |
| Text Primary | `#0F1419` | Near-black, WCAG AAA |
| Text Secondary | `#4B5563` | 60% opacity equivalent |
| Border | `#E8EEF2` | Soft visual separation |
| Accent (Green) | `#0D6E47` | Fresh, saturated (Pantone 18-0419) |
| Gold/Secondary | `#D4A72A` | Unchanged, works in both modes |

---

## 2.3 Dark Mode Palette

| Component | Dark | Purpose |
|-----------|------|---------|
| Background | `#0F1419` | Navy-black, reduces luminance stress |
| Sidebar/Topbar | `#1A2332` | Elevated from background, readable borders |
| Text Primary | `#E8EEF2` | Off-white, WCAG AAA |
| Text Secondary | `#B0B8C4` | 50% opacity |
| Border | `#2D3E52` | Visible but not harsh |
| Accent (Green) | `#20C997` | Brighter for visibility |
| Gold/Secondary | `#D4A72A` | Unchanged |

---

## 3. Apple Design Principles Applied

### 3.1 Response — Kill Latency
**Goal:** Interface responds instantly to input; latency breaks directness.

**Implementation:**
- Theme toggle highlights on `pointer-down` (not `click`)
- Nav items show `:active` feedback immediately
- No artificial delays on any critical path
- Topbar feedback <16ms (one frame at 60fps)

```css
.nav-item:active {
  transform: scale(0.97);
  background: var(--active-bg);
  /* Instant visual feedback, no delay */
}
```

---

### 3.2 Direct Manipulation — 1:1 Tracking
**Goal:** Touch/input stays glued to the element, respecting grab offset.

**Implementation:**
- Filter buttons highlight exactly where clicked (not centered)
- Sidebar nav items stay anchored to hover region
- Draggable elements (future) use `setPointerCapture` for tracking outside bounds

---

### 3.3 Interruptibility — The Core Principle
**Goal:** Every animation must be reversible and redirectable at any instant.

**Implementation:**
- **No fixed-duration `transition`** on gesture-driven elements
  - Use **springs** instead (see § 3.4)
  - Springs animate from *current* (presentation) value, not target value
- **No locking during motion** — input always processed
- **Reverse velocity smoothly** when interrupted
  - Spring library (CSS custom properties) handles velocity blending
  - Avoids "brick wall" velocity discontinuities

**Code Pattern:**
```css
/* WRONG: Locks input during transition, can't interrupt */
.filter-btn {
  transition: background 300ms ease-out;
}

/* RIGHT: Spring animation, interruptible at any frame */
.filter-btn {
  animation: spring-to-bg 0.4s cubic-bezier(0.17, 0.67, 0.83, 0.67);
}
```

---

### 3.4 Behavior Over Animation — Use Springs
**Goal:** Physics-based motion that responds naturally to input and velocity.

**Implementation:**
Use two designer-friendly spring parameters:

| Parameter | Purpose | Admin Values |
|-----------|---------|--------------|
| **Damping Ratio** | Controls overshoot; 1.0 = no bounce | 1.0 (critical) for UI, 0.8 for momentum gestures |
| **Response** | How quickly value reaches target, in seconds | 0.3–0.4s for most UI |

**Concrete Spring Configurations:**

| Interaction | Damping | Response | Why |
|-------------|---------|----------|-----|
| Nav item hover | 1.0 | 0.3s | Crisply animated, no bounce |
| Filter button press | 1.0 | 0.25s | Instant feedback, settling quickly |
| Stat card scale-in | 1.0 | 0.4s | Graceful entrance, non-distracting |
| Theme switch | 0.8 | 0.5s | Slight bounce because switching *is* a momentum event |
| Sidebar collapse (future) | 0.8 | 0.4s | Bouncy because drawer gestures carry inertia |

**CSS Implementation (via custom keyframes):**
```css
@keyframes spring-critical-damping {
  0% { transform: scale(0.95); opacity: 0; }
  60% { transform: scale(1.02); }
  100% { transform: scale(1); opacity: 1; }
}

.stat-card {
  animation: spring-critical-damping 0.4s ease-out forwards;
}
```

---

### 3.5 Velocity Handoff
**Goal:** Animation inherits gesture velocity; no seam between drag and snap.

**Implementation:**
- When filter buttons toggle, inherit pointer release velocity
- Topbar toggle respects click momentum (future, if draggable)
- Spring carries velocity into next animation on interrupt

---

### 3.6 Momentum Projection
**Goal:** Flicked elements overshoot intelligently, not just snap.

**Implementation:**
- Dashboard stat cards **stagger-enter** (not all at once)
  - Each card projects upward by 10px before settling
  - Creates sense of "material surfaces arriving"
- Filter selections **highlight outward** before settling

---

### 3.7 Spatial Consistency
**Goal:** If something leaves one way, it enters from where it came.

**Implementation:**
- **Topbar theme toggle:** Icon rotates in place, color updates
  - Doesn't slide; rotation origin is the icon center
- **Sidebar nav items:** Highlight grows *from left edge* (left-to-right language)
  - Indent border appears on left, background fills rightward
- **Modals & overlays:** 
  - Enter: fade + scale up from origin
  - Exit: scale down + fade, same origin

```css
.topbar-theme-toggle {
  transform-origin: center center;
  /* Rotation stays in place, doesn't drift */
}

.nav-item.active {
  border-left-color: var(--accent-gold);
  /* Border grows from left edge, visual path */
}
```

---

### 3.8 Materials & Translucency (Principle #12)
**Goal:** Layering with blur/frosted glass conveys hierarchy without opacity alone.

**Implementation:**

**Dark Mode:**
```css
.topbar, .sidebar {
  background: rgba(26, 35, 50, 0.85);
  backdrop-filter: blur(10px) saturate(1.2);
  border: 1px solid rgba(255, 255, 255, 0.08);
  /* Frosted glass effect; content scrolls behind */
}
```

**Light Mode:**
```css
.topbar, .sidebar {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px) saturate(1.1);
  border: 1px solid rgba(0, 0, 0, 0.06);
}
```

**Modals & Overlays:**
- Dim scrim with blur mask where floating UI overlaps content
- No double-translucent surfaces (legibility collapse)
- Vibrancy: higher contrast + slightly heavier weight on translucent layers

---

### 3.9 Reduced Motion & Accessibility
**Goal:** Respect user preferences; remove vestibular triggers without losing feedback.

**Implementation:**

```css
@media (prefers-reduced-motion: reduce) {
  /* Replace springs with 150ms opacity fade */
  * {
    animation-duration: 150ms !important;
    animation-timing-function: ease !important;
  }
  
  .stat-card, .filter-btn, .nav-item {
    animation: fade-in 150ms ease forwards;
  }
}

@media (prefers-reduced-transparency: reduce) {
  /* Solidify translucent surfaces */
  .topbar, .sidebar {
    background: var(--bg-secondary) !important;
    backdrop-filter: none !important;
    border: 1px solid var(--border-color);
  }
}

@media (prefers-contrast: more) {
  /* Increase border/text contrast */
  :root {
    --border-color: var(--text-secondary);
  }
}
```

---

## 4. Animation Vocabulary Applied

### 4.1 Entrances & Exits

**Scale-in:** Dashboard stat cards
- Start: 0.95 scale, opacity 0
- End: 1.0 scale, opacity 1
- Duration: 0.4s, damping 1.0, staggered 80–120ms

**Fade-in:** Background layers, modals
- Start: opacity 0
- End: opacity 1
- Duration: 0.2–0.3s, linear or ease-out

**Pop-in:** Notification badges, alerts
- Start: 0.85 scale, opacity 0
- Peak: 1.05 scale (slight overshoot)
- End: 1.0 scale
- Duration: 0.35s, damping 0.8 (bouncy)

---

### 4.2 Sequencing & Timing

**Stagger:** Dashboard stat cards enter one after another
```css
.stat-card:nth-child(1) { animation-delay: 0ms; }
.stat-card:nth-child(2) { animation-delay: 80ms; }
.stat-card:nth-child(3) { animation-delay: 160ms; }
/* ... up to 6 cards with 80ms intervals */
```

**Orchestration:** When theme switches
- Text color fades in parallel (same duration)
- Border colors transition together
- Background + backdrop-filter coordinate (material "arrives")

---

### 4.3 Movement & Transforms

**Translate:** Sidebar nav indicator
- Moves vertically to active item without rotate
- Smooth, spring-driven

**Rotate:** Theme toggle icon
- Spins 180° on click (sun ↔ moon)
- Stays in place (transform-origin: center)

**Scale:** Filter buttons, stat cards
- 0.97 on hover (press feedback)
- 1.0 on release (spring snaps back)

---

### 4.4 Interactions

**Press/Tap Feedback:**
- Nav items: `scale(0.97)` on `:active`
- Buttons: `scale(0.96)` + `box-shadow` fade on press
- Feedback visible <16ms

**Hover Effect:**
- Nav items: background + text color animate in
- Buttons: border color + shadow darken
- Duration: 200ms, ease-out

**Reduced Motion Equivalent:**
- No scale, just opacity change
- Duration still 150ms for consistency

---

## 5. Implementation Strategy

### Phase 1: CSS Refactor (Week 1)
**Deliverables:**
- [ ] Extract all hardcoded colors → CSS custom properties
- [ ] Create `:root` base + `@media (prefers-color-scheme)` overrides
- [ ] Define spring animation keyframes (@keyframes)
- [ ] Test light/dark toggling in DevTools

**Files:**
- `templates/admin/admin.html` — `:root` tokens, @keyframes, media queries

**Estimated Time:** 4–6 hours

---

### Phase 2: Topbar Theme Toggle (Week 1)
**Deliverables:**
- [ ] Add theme toggle button (sun/moon icon) in topbar
- [ ] Implement localStorage persistence (`powerwize-theme` key)
- [ ] Apply `data-theme="light" | "dark"` to `<html>`
- [ ] Test toggle across page sections

**Files:**
- `templates/admin/admin.html` — add toggle button
- `static/admin.js` — toggle handler + localStorage

**Estimated Time:** 2–3 hours

---

### Phase 3: Animations & Interactions (Week 2)
**Deliverables:**
- [ ] Implement stagger-in for stat cards
- [ ] Add spring animations to nav items (hover/active)
- [ ] Filter button press feedback (scale + color)
- [ ] Modal/overlay materialize animations
- [ ] Test interruptibility (click nav item mid-animation)

**Files:**
- `templates/admin/admin.html` — @keyframes, animation properties

**Estimated Time:** 6–8 hours

---

### Phase 4: Testing & Polish (Week 2)
**Deliverables:**
- [ ] Light/dark mode across all sections (Dashboard, Users, Schedules, etc.)
- [ ] Reduced motion compliance testing
- [ ] Color contrast audit (WCAG AAA)
- [ ] Animation smoothness (60fps target)
- [ ] Keyboard navigation + accessibility

**Files:**
- Test suite for all sections
- Accessibility audit report

**Estimated Time:** 4–5 hours

---

## 6. Color Palette Specification

### Light Mode (prefers-color-scheme: light)

```css
:root {
  /* Base */
  --bg-primary: #F8F9FA;
  --bg-secondary: #FFFFFF;
  --bg-tertiary: #F0F2F5;
  --text-primary: #0F1419;
  --text-secondary: #4B5563;
  --text-tertiary: #8B95A5;
  --border-color: #E8EEF2;
  
  /* Theme */
  --accent-green: #0D6E47;
  --accent-green-light: #E2F5EC;
  --accent-gold: #D4A72A;
  --accent-gold-light: #FEF3C7;
  
  /* Status */
  --status-success: #20C997;
  --status-success-light: #C3F9D6;
  --status-warning: #FFC107;
  --status-warning-light: #FFF3CD;
  --status-error: #DC3545;
  --status-error-light: #F8D7DA;
  
  /* Elevation */
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.12);
}
```

### Dark Mode (prefers-color-scheme: dark)

```css
@media (prefers-color-scheme: dark) {
  :root {
    /* Base */
    --bg-primary: #0F1419;
    --bg-secondary: #1A2332;
    --bg-tertiary: #23313E;
    --text-primary: #E8EEF2;
    --text-secondary: #B0B8C4;
    --text-tertiary: #7A8290;
    --border-color: #2D3E52;
    
    /* Theme */
    --accent-green: #20C997;
    --accent-green-light: #20C99720;
    --accent-gold: #D4A72A;
    --accent-gold-light: #D4A72A20;
    
    /* Status */
    --status-success: #51CF66;
    --status-success-light: #51CF6620;
    --status-warning: #FFD43B;
    --status-warning-light: #FFD43B20;
    --status-error: #FF8787;
    --status-error-light: #FF878720;
    
    /* Elevation */
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
    --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
    --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.5);
  }
}
```

---

## 7. Spring Animation Keyframes

### Critical Damping (1.0) — Scale In

```css
@keyframes spring-scale-in {
  0% {
    transform: scale(0.95);
    opacity: 0;
  }
  60% {
    transform: scale(1.01);
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
```

### Slightly Damped (0.8) — Pop In with Bounce

```css
@keyframes spring-pop-in {
  0% {
    transform: scale(0.85);
    opacity: 0;
  }
  65% {
    transform: scale(1.08);
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
```

### Press Feedback (Quick)

```css
@keyframes spring-press {
  0% {
    transform: scale(1);
  }
  100% {
    transform: scale(0.97);
  }
}
```

---

## 8. Component Animation Map

| Component | Animation | Duration | Damping | Stagger |
|-----------|-----------|----------|---------|---------|
| Stat Cards | spring-scale-in | 0.4s | 1.0 | 80ms |
| Filter Buttons | spring-press | 0.2s | 1.0 | — |
| Nav Items (Hover) | spring-highlight | 0.3s | 1.0 | — |
| Modal Overlay | fade-in | 0.2s | linear | — |
| Modals (Scale) | spring-scale-in | 0.35s | 0.8 | — |
| Notification Badges | spring-pop-in | 0.35s | 0.8 | — |
| Theme Switch | color-fade | 0.25s | linear | — |
| Table Rows (Hover) | background-fade | 0.15s | ease-out | — |

---

## 9. Accessibility Compliance

### WCAG 2.1 Level AAA

**Color Contrast:**
- Text on background: 7:1+ (AAA)
- UI components: 4.5:1+ (AA) or 3:1+ with 1.5px stroke
- Verify with WebAIM Contrast Checker

**Motion:**
- Prefers Reduced Motion: All springs → 150ms fade
- No more than 3 Hz flashing (not applicable)
- Parallax: Minimal (not used in admin dashboard)

**Keyboard Navigation:**
- All buttons/links: `:focus-visible` ring
- Tab order: left-to-right, top-to-bottom
- No keyboard traps

**Screen Readers:**
- Semantic HTML (`<button>`, `<nav>`, `<main>`)
- `aria-label` on icon-only buttons
- `aria-current="page"` on active nav items
- Status updates: `aria-live="polite"` for alerts

---

## 10. Testing Checklist

### Light Mode Testing
- [ ] All text meets WCAG AAA contrast (7:1)
- [ ] Icon visibility on light backgrounds
- [ ] Borders and shadows distinct
- [ ] Chart colors readable

### Dark Mode Testing
- [ ] Reduced eye strain (no pure white text)
- [ ] All text meets WCAG AAA (7:1)
- [ ] Material translucency readable
- [ ] Chart colors distinct

### Animation Testing
- [ ] Stat cards stagger smoothly (0–480ms total)
- [ ] Nav items responsive to hover (no lag)
- [ ] Filter buttons press feedback <16ms
- [ ] Theme toggle smooth (no flicker)
- [ ] No jank or dropped frames (60fps target)

### Accessibility Testing
- [ ] Keyboard-only navigation (no mouse)
- [ ] Screen reader announces active nav item
- [ ] Prefers Reduced Motion: animations replaced
- [ ] Focus visible on all interactive elements
- [ ] Color contrast 7:1+ everywhere

### Cross-Browser Testing
- [ ] Chrome/Edge (Windows)
- [ ] Firefox (Windows)
- [ ] Safari (macOS, if available)
- [ ] Mobile Safari (iOS)
- [ ] Chrome Mobile (Android)

---

## 11. File Changes Overview

### Primary Changes

| File | Change | Scope |
|------|--------|-------|
| `templates/admin/admin.html` | Add `:root` CSS vars, @keyframes, theme toggle button | ~200 lines |
| `static/admin-theme.js` (new) | Theme toggle handler + localStorage | ~50 lines |
| Entire `<style>` block | Replace hardcoded colors with CSS vars | Full refactor |

### No Template Changes Required
- Admin sections (Dashboard, Users, etc.) remain unchanged
- Only CSS and JavaScript added
- Backward compatible

---

## 12. Known Constraints & Workarounds

| Constraint | Impact | Workaround |
|-----------|--------|-----------|
| CSS-only theme switch | No server state | Use `localStorage` + `data-theme` attribute |
| No CSS Spring API | Must use @keyframes | Custom damping ratios in keyframes |
| Font rendering (DM Sans) | May differ light/dark | Test both modes, adjust letter-spacing if needed |
| Flatpickr overrides | Calendar ignores theme | Update `.flatpickr-*` selectors to use CSS vars |
| Chart.js colors | Hardcoded in JS | Extract to data attribute or re-initialize on theme toggle |

---

## 13. Timeline & Milestones

| Milestone | Target | Duration |
|-----------|--------|----------|
| **Phase 1: CSS Refactor** | 2026-08-23 | 1 day |
| **Phase 2: Theme Toggle** | 2026-08-24 | 1 day |
| **Phase 3: Animations** | 2026-08-28 | 3 days |
| **Phase 4: Testing** | 2026-08-31 | 2 days |
| **Handoff/Review** | 2026-09-02 | — |

---

## 14. Success Criteria

- ✅ Light and dark modes toggle seamlessly with localStorage persistence
- ✅ All animations smooth at 60fps with no jank
- ✅ Animations interruptible (can reverse mid-flight)
- ✅ Color contrast meets WCAG AAA (7:1 text, 3:1 UI)
- ✅ Reduced motion compliance tested
- ✅ Keyboard navigation fully functional
- ✅ No visible flicker on theme switch
- ✅ All sections (Dashboard, Users, Schedules, etc.) tested in both modes

---

## 15. References & Design Resources

### Apple Design Guidance
- [Designing Fluid Interfaces](https://developer.apple.com/videos/play/wwdc2018/803/) (WWDC 2018)
- [The Details of UI Typography](https://developer.apple.com/videos/play/wwdc2020/10175/) (WWDC 2020)
- [Designing Audio-Haptic Experiences](https://developer.apple.com/videos/play/wwdc2020/10079/) (WWDC 2020)

### Material Design & Accessibility
- [Material Design 3 Color](https://m3.material.io/styles/color/overview)
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)

### Animation Libraries (Optional, if needed)
- Framer Motion (React) — reference for spring math
- Motion One — lightweight, browser-native
- Animate.css — utility-based approach

---

## 16. Contact & Notes

**Designer/Owner:** Jan McZeal Bandao  
**Email:** bandao.janmczeal@gmail.com

**Open Questions:**
- Should theme preference sync across tabs? (Use SharedWorker or BroadcastChannel)
- Should charts re-initialize on theme switch, or use CSS filter to invert?
- Animated sidebar collapse in future release?

**Future Enhancements:**
1. Dark theme for the landing page (site_bp.py)
2. Gesture-driven interactions (drag to reorder, swipe to dismiss)
3. Haptic feedback on mobile (Vibration API)
4. Page transitions with View Transitions API
5. Animated charts (chart.js with spring easing)

---

**End of Admin Dashboard Design Document**  
Last Update: 2026-08-21  
Next Review: After Phase 4 testing
