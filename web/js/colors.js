// Color scales for SNOTEL variables. `bins` are thresholds; `colors` has one
// more entry than `bins` (values below the first threshold use colors[0]).
// Edit freely -- the legend is generated from these definitions.

const SNOTEL_VARS = {
  depth_24h: {
    label: "24-hr snow depth change (in)",
    bins: [-2, 1, 3, 6, 9, 12, 18, 24],
    colors: ["#a6761d", "#f0f0f0", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd",
             "#08519c", "#6a51a3", "#d03dcf"],
    signed: true, digits: 0,
  },
  depth_72h: {
    label: "72-hr snow depth change (in)",
    bins: [-4, 2, 6, 12, 18, 24, 36, 48],
    colors: ["#a6761d", "#f0f0f0", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd",
             "#08519c", "#6a51a3", "#d03dcf"],
    signed: true, digits: 0,
  },
  swe_24h: {
    label: "24-hr SWE change (in)",
    bins: [-0.3, 0.1, 0.25, 0.5, 1, 1.5, 2, 3],
    colors: ["#a6761d", "#f0f0f0", "#c7e9c0", "#a1d99b", "#74c476", "#31a354",
             "#006d2c", "#6a51a3", "#d03dcf"],
    signed: true, digits: 1,
  },
  depth_in: {
    label: "Snow depth (in)",
    bins: [1, 12, 24, 36, 48, 72, 96, 120],
    colors: ["#ffffff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6",
             "#2171b5", "#08519c", "#08306b"],
    digits: 0,
  },
  swe_in: {
    label: "Snow water equivalent (in)",
    bins: [0.1, 2, 4, 6, 8, 12, 16, 24, 32],
    colors: ["#ffffff", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d",
             "#238b45", "#006d2c", "#00441b", "#3f007d"],
    digits: 1,
  },
  pct_median: {
    label: "SWE % of median",
    bins: [25, 50, 70, 90, 110, 130, 150, 200],
    colors: ["#8c510a", "#bf812d", "#dfc27d", "#f6e8c3", "#f5f5f5", "#c7eae5",
             "#80cdc1", "#35978f", "#01665e"],
    digits: 0, suffix: "%",
  },
  temp_f: {
    label: "Air temperature (°F)",
    bins: [-10, 0, 10, 20, 28, 32, 36, 45, 55],
    colors: ["#4a1486", "#6a51a3", "#2171b5", "#4292c6", "#9ecae1", "#deebf7",
             "#fee0d2", "#fc9272", "#ef3b2c", "#a50f15"],
    digits: 0,
  },
};

function colorFor(spec, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  let i = 0;
  while (i < spec.bins.length && v >= spec.bins[i]) i++;
  return spec.colors[i];
}

// Dark or white text, whichever has the higher WCAG contrast on this background
// (relative luminance; PLAN.md §6-B: AA contrast for legend and swatch labels).
function textOn(hex) {
  const n = parseInt(hex.slice(1, 7), 16);
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return (L + 0.05) / (0.0056 + 0.05) >= 1.05 / (L + 0.05) ? "#111" : "#fff";
}

function fmtValue(spec, v) {
  if (v === null || v === undefined) return "–";
  const s = v.toFixed(spec.digits ?? 0);
  return (spec.signed && v > 0 ? "+" : "") + s + (spec.suffix || "");
}

// "Expected" (NBM's deterministic amount) explained in one place; shown as an ⓘ tooltip (owner S6).
const EXPECTED_TIP = "Expected = NBM's forecast amount, an average of possible outcomes. You typically have about a 1-in-3 chance of reaching it; the 10–90% range shows what's typical.";
const expectedInfo = () => `<a class="info" href="about.html#nbm" title="${EXPECTED_TIP}" aria-label="What Expected means">ⓘ</a>`;

// NAADS danger colors (match pipeline/avalanche.py)
const DANGER_TEXT = { 0: "#333", 1: "#fff", 2: "#333", 3: "#111", 4: "#fff", 5: "#fff" };

// Forecast snowfall (in): same bins/colors as the model maps (pipeline/models/plot.py
// SNOW, NWS-style). Shared by the area page, Powder Finder and legends (PLAN.md §6).
const SNOWFALL = {
  label: "Snowfall (in)",
  bins: [0.1, 1, 2, 3, 4, 6, 8, 12, 18, 24, 30, 36, 48],
  colors: ["#f4f6f8", "#bdd7e7", "#6baed6", "#3182bd", "#08519c", "#082694", "#ffff96", "#ffc400",
           "#ff8700", "#db1400", "#9e0000", "#690000", "#ccccff", "#9f8ccd"],
  digits: 0,
};

// Chance of at least X inches (%): sequential, shared by Powder Finder table/map and area charts.
const PROB = {
  label: "Chance (%)",
  bins: [5, 10, 20, 30, 50, 70, 90],
  colors: ["#f4f6f8", "#dbe9f6", "#b3d3ea", "#7fb2d9", "#4a8cc4", "#2b5fa6", "#5b3a9c", "#8e1f7a"],
  digits: 0,
};
