import animate from "tailwindcss-animate";
import type { Config } from "tailwindcss";

/**
 * The CCDS token set, expressed as Tailwind theme keys.
 *
 * Nothing in `src/` may reach past this file to a raw hex or a raw pixel: if a value is needed on
 * a screen it is named here first. The two groups below are deliberate - `colors` exposes the
 * semantic layer under both its CCDS name and the shorter alias the existing screens were written
 * against, and both resolve to the same variable, so there is one palette and not two.
 */
const alpha = (token: string) => `hsl(var(${token}) / <alpha-value>)`;

const pillHues = [
  "purple",
  "pink",
  "blue",
  "sky",
  "red",
  "mint",
  "teal",
  "cyan",
  "rose",
  "amber",
  "green",
  "yellow",
  "orange",
] as const;

const pill = Object.fromEntries(
  pillHues.map((hue) => [
    hue,
    {
      bg: alpha(`--pill-${hue}-bg`),
      text: alpha(`--pill-${hue}-text`),
      border: alpha(`--pill-${hue}-border`),
    },
  ]),
);

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic layer, under its CCDS names.
        text: {
          default: alpha("--color-text-default"),
          subtle: alpha("--color-text-subtle"),
          inverse: alpha("--color-text-inverse"),
          brand: alpha("--color-text-brand"),
          danger: alpha("--color-text-danger"),
          success: alpha("--color-text-success"),
          warning: alpha("--color-text-warning"),
          link: alpha("--color-link-default"),
        },
        icon: {
          default: alpha("--color-icon-default"),
          subtle: alpha("--color-icon-subtle"),
          inverse: alpha("--color-icon-inverse"),
          brand: alpha("--color-icon-brand"),
          danger: alpha("--color-icon-danger"),
          success: alpha("--color-icon-success"),
          warning: alpha("--color-icon-warning"),
        },
        elevation: {
          default: alpha("--elevation-surface-default"),
          sunken: alpha("--elevation-surface-sunken"),
          raised: alpha("--elevation-surface-raised"),
          "raised-hovered": alpha("--elevation-surface-raised-hovered"),
          "raised-pressed": alpha("--elevation-surface-raised-pressed"),
          overlay: alpha("--elevation-surface-overlay"),
          "overlay-hovered": alpha("--elevation-surface-overlay-hovered"),
          "overlay-pressed": alpha("--elevation-surface-overlay-pressed"),
          hovered: alpha("--elevation-surface-hovered"),
          pressed: alpha("--elevation-surface-pressed"),
        },
        pill,
        brand: {
          DEFAULT: alpha("--color-background-brand-bold"),
          bold: alpha("--color-background-brand-bold"),
          subtle: alpha("--color-background-information"),
        },
        danger: {
          DEFAULT: alpha("--color-background-danger"),
          bold: alpha("--color-background-danger-bold"),
        },
        warning: {
          DEFAULT: alpha("--color-background-warning"),
          bold: alpha("--color-background-warning-bold"),
        },
        success: {
          DEFAULT: alpha("--color-background-success"),
          bold: alpha("--color-background-success-bold"),
        },
        information: {
          DEFAULT: alpha("--color-background-information"),
          bold: alpha("--color-background-information-bold"),
        },
        discovery: alpha("--color-background-discovery"),
        selected: alpha("--color-background-selected"),

        // Aliases. Same variables, shorter names, so the existing screens stay valid.
        background: {
          DEFAULT: alpha("--background"),
          neutral: alpha("--color-background-neutral"),
          "neutral-bold": alpha("--color-background-neutral-bold"),
          input: alpha("--color-background-input"),
          disabled: alpha("--color-background-disabled"),
          selected: alpha("--color-background-selected"),
        },
        foreground: alpha("--foreground"),
        border: {
          DEFAULT: alpha("--border"),
          bold: alpha("--color-border-bold"),
          brand: alpha("--color-border-brand"),
          danger: alpha("--color-border-danger"),
          success: alpha("--color-border-success"),
          warning: alpha("--color-border-warning"),
        },
        input: alpha("--input"),
        ring: alpha("--ring"),
        card: {
          DEFAULT: alpha("--card"),
          foreground: alpha("--card-foreground"),
        },
        popover: {
          DEFAULT: alpha("--popover"),
          foreground: alpha("--popover-foreground"),
        },
        primary: {
          DEFAULT: alpha("--primary"),
          foreground: alpha("--primary-foreground"),
        },
        secondary: {
          DEFAULT: alpha("--secondary"),
          foreground: alpha("--secondary-foreground"),
        },
        accent: {
          DEFAULT: alpha("--accent"),
          foreground: alpha("--accent-foreground"),
        },
        muted: {
          DEFAULT: alpha("--muted"),
          foreground: alpha("--muted-foreground"),
        },
        destructive: {
          DEFAULT: alpha("--destructive"),
          foreground: alpha("--destructive-foreground"),
        },
        surface: {
          DEFAULT: alpha("--surface"),
          foreground: alpha("--surface-foreground"),
        },
        sidebar: {
          DEFAULT: alpha("--sidebar"),
          foreground: alpha("--sidebar-foreground"),
          muted: alpha("--sidebar-muted"),
          active: alpha("--sidebar-active"),
          border: alpha("--sidebar-border"),
        },
        signal: {
          confident: alpha("--signal-confident"),
          review: alpha("--signal-review"),
          blocked: alpha("--signal-blocked"),
        },
        chart: {
          1: alpha("--chart-1"),
          2: alpha("--chart-2"),
          3: alpha("--chart-3"),
          4: alpha("--chart-4"),
          "phase-1": alpha("--chart-phase-1"),
          "phase-2": alpha("--chart-phase-2"),
          "phase-3": alpha("--chart-phase-3"),
          "phase-4": alpha("--chart-phase-4"),
          "phase-5": alpha("--chart-phase-5"),
          grid: alpha("--chart-grid"),
        },
      },
      // Space/*, on the 4px grid. Tailwind's own numeric scale sits on the same grid, so `p-4`
      // and `p-space-200` are the same 16px - the named form is for anywhere the token matters
      // more than the number. Dimension/* and Icon Size/* ride the same map so `h-control-md`
      // and `size-icon-small` work.
      spacing: {
        "space-0": "0px",
        "space-025": "2px",
        "space-050": "4px",
        "space-075": "6px",
        "space-100": "8px",
        "space-150": "12px",
        "space-200": "16px",
        "space-250": "20px",
        "space-300": "24px",
        "space-400": "32px",
        "space-500": "40px",
        "space-600": "48px",
        "space-800": "64px",
        "space-1000": "80px",
        "control-xs": "24px",
        "control-sm": "28px",
        "control-md": "36px",
        "control-lg": "44px",
        "control-xl": "52px",
        "icon-small": "16px",
        "icon-medium": "20px",
        "icon-large": "24px",
        "icon-xlarge": "32px",
      },
      borderRadius: {
        none: "0px",
        small: "4px",
        control: "var(--radius-control)",
        medium: "var(--radius)",
        large: "12px",
        xlarge: "16px",
        // Aliases, so `rounded-sm|md|lg` land on the CCDS steps rather than Tailwind defaults.
        sm: "4px",
        md: "var(--radius)",
        lg: "12px",
      },
      borderWidth: {
        none: "0px",
        thin: "1px",
        thick: "2px",
      },
      ringWidth: {
        thin: "1px",
        thick: "2px",
      },
      opacity: {
        hover: "0.08",
        pressed: "0.12",
        disabled: "0.4",
        loading: "0.6",
        scrim: "0.5",
      },
      boxShadow: {
        raised: "var(--shadow-raised)",
      },
      backgroundImage: {
        "brand-gradient": "var(--brand-gradient)",
      },
      fontFamily: {
        sans: [
          "var(--font-funnel-display)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        heading: [
          "var(--font-funnel-display)",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
      },
      // The CCDS type ramp. Line heights are the ones the rendered instances carry, not a ratio
      // applied after the fact.
      fontSize: {
        "body-xs": ["11px", "16px"],
        "body-sm": ["12px", "16px"],
        "body-md": ["14px", "20px"],
        "body-lg": ["16px", "24px"],
        "body-xl": ["18px", "28px"],
        "label-md": ["14px", "20px"],
        "label-lg": ["16px", "20px"],
        h6: ["14px", "20px"],
        h5: ["16px", "24px"],
        h4: ["18px", "26px"],
        h3: ["20px", "28px"],
        h2: ["24px", "32px"],
        h1: ["32px", "40px"],
      },
      screens: {
        sm: "480px",
        md: "768px",
        lg: "1024px",
        xl: "1280px",
      },
      zIndex: {
        base: "0",
        raised: "100",
        dropdown: "200",
        sticky: "300",
        overlay: "400",
        modal: "500",
        popover: "600",
        toast: "700",
      },
      transitionDuration: {
        DEFAULT: "100ms",
        instant: "0ms",
        fast: "100ms",
        medium: "200ms",
        slow: "350ms",
      },
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.2, 0, 0, 1)",
        standard: "cubic-bezier(0.2, 0, 0, 1)",
        enter: "cubic-bezier(0, 0, 0, 1)",
        exit: "cubic-bezier(0.2, 0, 1, 1)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(2px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 200ms cubic-bezier(0, 0, 0, 1)",
        "accordion-up": "accordion-up 200ms cubic-bezier(0.2, 0, 1, 1)",
        "fade-in": "fade-in 200ms cubic-bezier(0, 0, 0, 1)",
      },
    },
  },
  plugins: [animate],
};

export default config;
