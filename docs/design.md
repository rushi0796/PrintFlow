# PrintFlow — Design System & UI Specification

## 1. Color Palette & Theme

The PrintFlow design system combines modern indigo accents with deep slate tones, emerald indicators, and a signature metallic hood receipt finish.

| Semantic Name | Hex Code / Value | Usage |
|---|---|---|
| **Brand Primary** | `#4f46e5` (Indigo-600) | Primary CTA buttons, active selection states, key links |
| **Primary Hover** | `#4338ca` (Indigo-700) | Hover/focus states for primary interactive elements |
| **Secondary Accent** | `#0284c7` (Sky-600) | Secondary badges, progress bars, active toggles |
| **Success / Printed** | `#059669` (Emerald-600) | Status LED online indicator, completion badges, safe privacy alerts |
| **Warning / Queued** | `#d97706` (Amber-600) | Pending queue status, processing spinners |
| **Danger / Failed** | `#dc2626` (Red-600) | Error messages, failed job alerts, retry triggers |
| **Background Dark** | `#0f172a` (Slate-900) | Top navbars, receipt modal backdrop, dark theme panels |
| **Surface Card** | `#ffffff` / `#1e293b` | Elevated content cards, document settings container |
| **Metallic Gold Hood**| `linear-gradient(135deg, #d4af37, #aa7c11)` | Receipt printer top slot hood |
| **Receipt Paper** | `#ffffff` (Pattern shadow) | Animated emerging physical receipt ticket |

---

## 2. Typography

### Primary Font Family
```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
```

### Monospace (Receipt & Technical Data)
```css
font-family: 'Courier New', Courier, monospace;
```

### Scale & Hierarchy

| Element | Size | Weight | Line Height | Case / Tracking |
|---|---|---|---|---|
| **Display Header (H1)** | `1.875rem` (30px) | `700` (Bold) | `1.2` | Tight tracking |
| **Section Header (H2)** | `1.375rem` (22px) | `600` (SemiBold) | `1.3` | Normal |
| **Card Header (H3)** | `1.125rem` (18px) | `600` (SemiBold) | `1.4` | Normal |
| **Body Large** | `1.000rem` (16px) | `400` / `500` | `1.5` | Normal |
| **Body Standard** | `0.875rem` (14px) | `400` | `1.5` | Normal |
| **Caption / Badge** | `0.750rem` (12px) | `500` / `600` | `1.4` | Uppercase |
| **Receipt Ticket Text**| `0.8125rem` (13px)| `600` (Mono) | `1.6` | Upper / Monospace |

---

## 3. UI Style & Design Principles

- **Modern & Premium**: Clean card layouts with smooth borders (`border-radius: 12px` / `16px`), subtle drop shadows (`0 10px 25px -5px rgba(0,0,0,0.1)`), and micro-interactions.
- **Trustworthy & Clean**: High contrast text ratios meeting WCAG AA accessibility standards.
- **Micro-Feedback**: Instant visual response on configuration toggles (Standard vs Micro Xerox mode, B&W vs Colour, Single vs Double-sided).

---

## 4. Responsive Layout Breakpoints

PrintFlow is designed mobile-first and scales seamlessly without horizontal scroll overflow:

- **Mobile Small / Medium**: `375px` to `639px` (Stacked single-column layout, bottom sticky checkout bar).
- **Tablet / Small Laptop**: `640px` to `1023px` (Two-column layout: settings panel left, Live Preview right).
- **Desktop / Wide Screen**: `1024px` to `1440px+` (Max container width `1200px`, centered layout with metallic receipt modal overlay).

---

## 5. Animated Metallic Receipt Printer Success UI

Visual Inspiration & Adaptations:
- **Metallic Top Hood**: Top-mounted brushed metallic gold slot (`#d4af37`) with dark interior shadow representing the physical printer output slot.
- **Status LED Indicator**: Pulsing emerald green LED (`#10b981`) indicating active hardware spooling.
- **Downward Emerging Animation**: Receipt paper slide animation (`keyframes receiptRollDown`) emerging downwards out of the metallic hood slot.
- **Real Order Data**: Receipt ticket dynamically displays:
  - PrintFlow Logo & Receipt Header
  - Order ID & Timestamp
  - Uploaded Filename & Total Pages
  - Print Mode (Standard vs Micro Xerox N-up)
  - Color Mode (B&W / Colour) & Duplex Side (Single / Double)
  - Paper Size & Orientation
  - Total Paid Amount (₹ INR)
  - Dynamic Order Status Badge (`PRINT_QUEUED` -> `PRINTING` -> `COMPLETED`)
  - Automated Privacy Badge: `"✓ Your files are safe. Documents securely deleted post-print."`
- **Interactive Controls**: Free Retry button (`/api/orders/{order_id}/retry`) and Return to Home button.
- **Silent & Data-Driven**: Animation is silent (no synthetic audio) and strictly driven by real backend polling state updates from `/api/orders/{order_id}/status`.
