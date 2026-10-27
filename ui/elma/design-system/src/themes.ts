/* Theme registry — the 12-step brightness ladder, dark→light (ux-ui-guide.md §1.7).
 * The ThemeSwitcher reads this to render the picker; each entry's `id` is what
 * goes in `data-theme`. Swatch colors (bg/accent) mirror tokens.css so the
 * switcher can paint previews without resolving CSS custom properties. */
export type Theme = {
  id: string;
  name: string;
  accent: string;
  bg: string;
  light: boolean;
};

export const THEMES: Theme[] = [
  {
    id: 'ironbark',
    name: 'Ironbark',
    accent: 'oklch(0.665 0.142 33)',
    bg: 'oklch(0.150 0.013 33)',
    light: false,
  },
  {
    id: 'bloodwood',
    name: 'Bloodwood',
    accent: 'oklch(0.665 0.142 20)',
    bg: 'oklch(0.190 0.013 20)',
    light: false,
  },
  {
    id: 'redwood',
    name: 'Redwood',
    accent: 'oklch(0.665 0.142 42)',
    bg: 'oklch(0.235 0.013 42)',
    light: false,
  },
  {
    id: 'mahogany',
    name: 'Mahogany',
    accent: 'oklch(0.665 0.142 66)',
    bg: 'oklch(0.285 0.013 66)',
    light: false,
  },
  {
    id: 'cedar',
    name: 'Cedar',
    accent: 'oklch(0.665 0.142 98)',
    bg: 'oklch(0.345 0.013 98)',
    light: false,
  },
  {
    id: 'evergreen',
    name: 'Evergreen',
    accent: 'oklch(0.665 0.142 152)',
    bg: 'oklch(0.408 0.013 152)',
    light: false,
  },
  {
    id: 'driftwood',
    name: 'Driftwood',
    accent: 'oklch(0.665 0.142 196)',
    bg: 'oklch(0.478 0.013 196)',
    light: false,
  },
  {
    id: 'amber',
    name: 'Amber',
    accent: 'oklch(0.48 0.155 62)',
    bg: 'oklch(0.700 0.014 62)',
    light: true,
  },
  {
    id: 'sandstone',
    name: 'Sandstone',
    accent: 'oklch(0.48 0.155 34)',
    bg: 'oklch(0.740 0.02 34)',
    light: true,
  },
  {
    id: 'oat',
    name: 'Oat',
    accent: 'oklch(0.48 0.155 88)',
    bg: 'oklch(0.808 0.02 88)',
    light: true,
  },
  {
    id: 'birch',
    name: 'Birch',
    accent: 'oklch(0.48 0.155 44)',
    bg: 'oklch(0.888 0.02 44)',
    light: true,
  },
  {
    id: 'paper',
    name: 'Paper',
    accent: 'oklch(0.48 0.155 32)',
    bg: 'oklch(0.964 0.02 32)',
    light: true,
  },
];

export const DEFAULT_THEME = 'redwood';
export const THEME_STORAGE_KEY = 'arbol-theme';
