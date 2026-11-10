/** Page-number handling for the PDF viewer, kept free of pdf.js so it can be unit-tested. */
export const ZOOM_STEP = 1.25;
export const clampPage = (n: number, pages: number) => Math.min(Math.max(1, Math.round(n) || 1), Math.max(1, pages));
