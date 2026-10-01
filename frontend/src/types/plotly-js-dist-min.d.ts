/** plotly.js-dist-min ships no type declarations; ChartPanel.tsx dynamic-imports it and only
 * uses `.newPlot(...)`, so a blanket module declaration (treated as `any`) is sufficient here. */
declare module "plotly.js-dist-min";
