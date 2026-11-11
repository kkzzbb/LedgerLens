# LedgerLens frontend

React + TypeScript on Vite. For now it is only a placeholder page with the
"LedgerLens" heading; real pages come in later tasks.

Requires Node 22 (22.12 or newer, see `.nvmrc`) and npm.

## Commands

Run from `frontend/`:

- `npm ci` - install dependencies from `package-lock.json`
- `npm run dev` - dev server on http://localhost:5173 (fails if the port is taken)
- `npm run lint` - ESLint over the whole project, warnings fail
- `npm run typecheck` - `tsc` (strict) over app code, tests and config files
- `npm test` - Vitest, run once
- `npm run build` - type check, then production build into `dist/`

## Layout

- `src/` - app code. Tests sit next to the code they test as `*.test.tsx`
- `src/setupTests.ts` - registers the jest-dom matchers for Vitest
- `vite.config.ts` - Vite and Vitest configuration
- `eslint.config.js` - ESLint configuration
