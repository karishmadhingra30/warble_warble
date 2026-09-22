/*
  app.js - everything the page does.

  The page does very little on purpose. All the downloading, filtering and
  arithmetic happened once, on a laptop, in the Python pipeline. What arrives
  here is a small JSON file of finished numbers. This file's whole job is to
  read that file, write one honest sentence about it, and draw it.

  No framework, no bundler, no npm. Two globals: Chart (from the CDN script in
  index.html) and this file.
*/

'use strict';

// Where the finished numbers live. A relative path, so the site works the
// same at a github.io subpath as it does on localhost.
const DATA_URL = 'data/arrivals.json';

// Pulled from the stylesheet rather than hard-coded, so light and dark mode
// both get the right values and the colours are defined in exactly one place.
function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

// Month names spelled out rather than taken from the browser's locale, so
// every reader sees the same label and a screenshot in the README matches
// what the page shows.
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Render a day-of-year number as a calendar date, e.g. "April 5".
 *
 * Nobody thinks in "day 95". Every number that reaches the reader goes
 * through here.
 *
 * Two details that have to match the Python side exactly, or the page will
 * disagree with the JSON it is reading:
 *
 *  - 2001 is the reference year. It is not a leap year, which is the whole
 *    point: the pipeline already removed 29 February from its day numbers,
 *    so translating them back through a leap year would shift every date
 *    after February by one day.
 *  - Halves round up, the way people expect. A window's arrival date is a
 *    median, and the median of an even number of years lands on a half day.
 */
function formatDay(doy) {
  if (doy === null || doy === undefined) return 'no data';
  const whole = Math.min(365, Math.max(1, Math.floor(doy + 0.5)));
  // Built in UTC throughout, so a reader east of Greenwich does not see
  // every date slip back by one.
  const when = new Date(Date.UTC(2001, 0, 1) + (whole - 1) * 86400000);
  return `${MONTH_NAMES[when.getUTCMonth()]} ${when.getUTCDate()}`;
}

/** "7 days earlier", "3 days later", or "no change". */
function formatShift(days) {
  if (days === null || days === undefined) return 'not enough data';
  if (days === 0) return 'no change';
  const magnitude = Math.abs(days);
  const unit = magnitude === 1 ? 'day' : 'days';
  return `${magnitude} ${unit} ${days < 0 ? 'earlier' : 'later'}`;
}

/** The median of an array of numbers. Returns null for an empty array. */
function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// ---------------------------------------------------------------------------
// Which rows are which
// ---------------------------------------------------------------------------

/** Birds whose shift we are willing to read as a migration result. */
function migrants(data) {
  return data.species.filter(
    (s) => !s.is_control && s.reliability !== 'excluded' && s.shift_days !== null
  );
}

/** The resident controls, which measure the method rather than the birds. */
function controls(data) {
  return data.species.filter((s) => s.is_control && s.shift_days !== null);
}

// ---------------------------------------------------------------------------
// The headline sentence, written from the data
// ---------------------------------------------------------------------------

/**
 * Build the one-sentence answer.
 *
 * This is deliberately grudging. The honest result of this project might well
 * be "not much changed", and a page that can only say "birds are arriving
 * earlier!" would be a page that was never really asking the question. So the
 * sentence is assembled from the numbers, including the control correction,
 * and it is allowed to come out boring.
 */
function buildAnswer(data) {
  const warblerShifts = migrants(data).map((s) => s.shift_days);
  const controlShifts = controls(data).map((s) => s.shift_days);

  if (!warblerShifts.length) {
    return {
      answer: 'There is not enough usable data to answer the question.',
      subhead: 'Every species fell below the minimum number of sightings, or was excluded.',
    };
  }

  const warblerMedian = median(warblerShifts);
  const controlMedian = median(controlShifts) ?? 0;
  // The controls cannot have changed their arrival date, so whatever they
  // show is measurement drift. Subtracting it leaves the part of the warbler
  // movement that drift does not explain.
  const corrected = warblerMedian - controlMedian;
  const earlierCount = warblerShifts.filter((d) => d < 0).length;
  const laterCount = warblerShifts.filter((d) => d > 0).length;

  // Round the signed number once and read the magnitude off that. Rounding
  // the magnitude separately makes -4.5 come out as "5 days" in one sentence
  // and "4 days" in the next.
  const roundedCorrected = Math.round(corrected);
  const size = Math.abs(roundedCorrected);

  // The noise floor, taken from the data rather than picked: the largest
  // apparent shift any resident bird showed. Those birds cannot have changed
  // their arrival date at all, so that number is what this method produces
  // out of nothing. A warbler signal smaller than it is not a finding, and
  // the page must not dress it up as one.
  const noiseFloor = controlShifts.length
    ? Math.max(...controlShifts.map((d) => Math.abs(d)))
    : 2;

  let answer;

  if (size <= noiseFloor) {
    answer =
      'Barely. California’s warblers do arrive a little earlier than they ' +
      'did fifteen years ago, but almost all of that disappears once you ' +
      'subtract the same drift the resident control birds show. A clear ' +
      '"not much changed" is still an answer.';
  } else if (earlierCount > laterCount && corrected < 0) {
    answer =
      `Most of California’s warblers now arrive about ${Math.round(size)} ` +
      `day${Math.round(size) === 1 ? '' : 's'} earlier in spring than they did ` +
      'fifteen years ago, after correcting for how much the measurement itself drifted.';
  } else if (laterCount > earlierCount && corrected > 0) {
    answer =
      `Most of California’s warblers now arrive about ${Math.round(size)} ` +
      `day${Math.round(size) === 1 ? '' : 's'} later in spring than they did ` +
      'fifteen years ago, after correcting for measurement drift.';
  } else {
    answer =
      'California’s warblers have not moved together. Some arrive earlier, ' +
      'some later, and the middle of the pack barely moved.';
  }

  const subhead =
    `${earlierCount} of ${warblerShifts.length} species arrived earlier. ` +
    `The median warbler shift is ${formatShift(Math.round(warblerMedian))}. ` +
    `The resident birds, which cannot have changed at all, shifted ` +
    `${formatShift(Math.round(controlMedian))} by the same method \u2014 so ` +
    `${formatShift(roundedCorrected)} is what survives the correction, ` +
    `against a noise floor of ${noiseFloor} day${noiseFloor === 1 ? '' : 's'}.`;

  return { answer, subhead };
}

// ---------------------------------------------------------------------------
// The main chart
// ---------------------------------------------------------------------------

// Below this width the chart is drawn for a phone: wrapped species labels and
// taller rows. 600px is where "Black-throated Gray Warbler" stops fitting on
// one line beside a usable plot area.
const NARROW_WIDTH = 600;

function isNarrow() {
  return window.innerWidth < NARROW_WIDTH;
}

/**
 * Break a species name into lines short enough to fit the axis gutter.
 *
 * Chart.js renders an array of strings as a multi-line tick label. Without
 * this, a long name on a phone gets silently cut off from the left, so
 * "Black-throated Gray Warbler" reads as "-throated Gray Warbler", which
 * looks like a bug in the data rather than a layout problem.
 */
function wrapLabel(text, maxChars) {
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const word of words) {
    if (line && (line + ' ' + word).length > maxChars) {
      lines.push(line);
      line = word;
    } else {
      line = line ? line + ' ' + word : word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

/**
 * Draw the dumbbell chart: one row per species, a dot for each window, a line
 * between them.
 *
 * Why a dumbbell and not two bars or a slope chart: the question is "how far
 * did this date move, and in which direction", and a dumbbell puts both the
 * distance and the direction on one short line you can read at a glance.
 *
 * The chart is built from three Chart.js datasets stacked on the same rows:
 * a very thin floating bar (the connecting line), a hollow dot (the early
 * window) and a filled dot (the late window). Fill carries the window, so the
 * two windows are still distinguishable with the colour removed.
 */
let mainChart = null;

function drawMainChart(data) {
  // Excluded species are left out of this chart on purpose. Their arrival
  // date is not an arrival date (wintering birds dominate the early part of
  // their spring), so plotting it beside the others would invite exactly the
  // comparison the exclusion exists to prevent. They are named underneath.
  const rows = data.species.filter(
    (s) => s.shift_days !== null && s.reliability !== 'excluded'
  );
  if (!rows.length) return;

  const labels = rows.map((s) => s.common_name);
  const colorFor = (s) =>
    s.is_control ? cssColor('--series-control')
      : s.reliability === 'flagged' ? cssColor('--series-flagged')
        : cssColor('--series-migrant');
  const colors = rows.map(colorFor);
  const surface = cssColor('--surface-card');
  const allDays = rows.flatMap((s) => [s.early_arrival_doy, s.late_arrival_doy]);

  // Snap the axis to whole multiples of the tick step.
  //
  // Chart.js always draws a tick exactly at an explicit `min`, and then its
  // next tick at the following round number. When those two are a few days
  // apart the labels are drawn on top of each other ("January 13" printed
  // over "January 20"). Choosing the step ourselves and snapping the bounds
  // to it means every tick lands on a multiple of the step and they are
  // evenly spaced by construction.
  const tickStep = isNarrow() ? 40 : 20;
  const axisMin = Math.max(1, Math.floor((Math.min(...allDays) - 4) / tickStep) * tickStep);
  const axisMax = Math.ceil((Math.max(...allDays) + 4) / tickStep) * tickStep;

  // Height grows with the number of rows so the x-axis band is never squeezed
  // out, and grows again on a phone where the labels wrap to two lines.
  const narrow = isNarrow();
  const rowHeight = narrow ? 58 : 42;
  const box = document.getElementById('main-chart-box');
  box.style.height = (rows.length * rowHeight + 76) + 'px';

  const canvas = document.getElementById('main-chart');

  mainChart = new Chart(canvas, {
    data: {
      labels,
      datasets: [
        {
          // The connector. A floating bar: each value is [from, to].
          type: 'bar',
          label: 'change',
          data: rows.map((s) => [s.early_arrival_doy, s.late_arrival_doy]),
          backgroundColor: colors,
          borderWidth: 0,
          barThickness: 3,
          order: 3,
        },
        {
          type: 'scatter',
          label: `${data.windows.early[0]}–${data.windows.early[1]}`,
          data: rows.map((s, i) => ({ x: s.early_arrival_doy, y: labels[i] })),
          pointRadius: 6,
          pointHoverRadius: 8,
          // Hollow: the fill is the card surface, so the dot reads as an
          // outline rather than as a second colour.
          backgroundColor: surface,
          borderColor: colors,
          borderWidth: 2,
          order: 2,
        },
        {
          type: 'scatter',
          label: `${data.windows.late[0]}–${data.windows.late[1]}`,
          data: rows.map((s, i) => ({ x: s.late_arrival_doy, y: labels[i] })),
          pointRadius: 6,
          pointHoverRadius: 8,
          backgroundColor: colors,
          // A 2px ring in the surface colour keeps the filled dot readable
          // where it overlaps the connector.
          borderColor: surface,
          borderWidth: 2,
          order: 1,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      responsive: true,
      layout: { padding: { right: 8 } },
      scales: {
        x: {
          type: 'linear',
          // Framed on the data with a few days of air either side. Starting at
          // day 0 would squeeze every dumbbell into the right-hand third.
          // Hard bounds rather than suggestions: the connector is a bar
          // dataset, and Chart.js pulls a bar's value axis back to zero
          // unless told otherwise, which would squash every dumbbell.
          min: axisMin,
          max: axisMax,
          title: { display: true, text: 'arrival date', color: cssColor('--text-muted') },
          ticks: {
            color: cssColor('--text-secondary'),
            // Whole days only. Two ticks a third of a day apart would print
            // the same calendar date twice.
            precision: 0,
            stepSize: tickStep,
            callback: (value) =>
              (Number.isInteger(value) ? formatDay(value) : null),
            maxRotation: 0,
            // Generous, because these labels are words rather than numbers
            // and "September 30" is wide.
            autoSkipPadding: 28,
          },
          grid: { color: cssColor('--grid'), drawTicks: false },
          border: { color: cssColor('--border') },
        },
        y: {
          type: 'category',
          ticks: {
            color: cssColor('--text-primary'),
            font: { size: narrow ? 11 : 13 },
            // Wrap rather than let Chart.js crop from the left.
            callback: (value, index) => wrapLabel(labels[index], narrow ? 16 : 30),
            autoSkip: false,
          },
          grid: { display: false },
          border: { color: cssColor('--border') },
        },
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'start',
          labels: {
            color: cssColor('--text-secondary'),
            usePointStyle: true,
            boxWidth: 8,
            // The connector dataset is scaffolding, not a series, so it is
            // kept out of the legend.
            filter: (item) => item.text !== 'change',
            // Chart.js orders legend entries by draw order, which puts the
            // late window first. Readers expect them chronologically.
            sort: (a, b) => a.text.localeCompare(b.text),
            padding: 18,
          },
        },
        tooltip: {
          callbacks: {
            title: (items) => rows[items[0].dataIndex].common_name,
            label: (item) => {
              const row = rows[item.dataIndex];
              if (item.dataset.type === 'bar') return formatShift(row.shift_days);
              return `${item.dataset.label}: ${formatDay(item.parsed.x)}`;
            },
          },
        },
      },
    },
  });
}

/**
 * Redraw the main chart when the window crosses the phone/desktop boundary.
 *
 * Chart.js resizes itself, but the row height and the label wrapping are
 * decided once at draw time. Rotating a phone, or dragging a desktop window
 * narrow, would otherwise leave the old layout in place.
 */
function watchWidth(data, selectSpecies) {
  let wasNarrow = isNarrow();
  let timer = null;
  window.addEventListener('resize', () => {
    // Debounced: a drag fires resize dozens of times a second, and rebuilding
    // a chart on every one of them is wasteful and visibly janky.
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (isNarrow() === wasNarrow) return;
      wasNarrow = isNarrow();
      if (mainChart) mainChart.destroy();
      drawMainChart(data);
      wireMainChartClicks(data, selectSpecies);
    }, 200);
  });
}

/**
 * Let a click on a row of the main chart open that species' detail view.
 *
 * Added on top of the buttons, never instead of them: a canvas cannot be
 * tabbed to or announced, so it can offer a shortcut but must not be the
 * only way in.
 */
function wireMainChartClicks(data, selectSpecies) {
  if (!mainChart) return;
  const canvas = document.getElementById('main-chart');
  canvas.style.cursor = 'pointer';
  canvas.addEventListener('click', (event) => {
    // 'y' mode with intersect false means "whichever row the pointer is
    // nearest vertically", so the whole row is a hit target, not just the dot.
    const hits = mainChart.getElementsAtEventForMode(
      event, 'y', { intersect: false }, true
    );
    if (!hits.length) return;
    const name = mainChart.data.labels[hits[0].index];
    const row = data.species.find((s) => s.common_name === name);
    if (row) {
      selectSpecies(row);
      document.getElementById('detail-panel').scrollIntoView({ behavior: 'smooth' });
    }
  });
}

/**
 * Fill in the colour key under the main chart.
 *
 * Chart.js's own legend explains the two windows (hollow dot, filled dot).
 * It cannot explain what the colours mean, because colour here separates
 * kinds of bird rather than datasets. This writes that second key in plain
 * HTML, so the meaning of every colour on the page is stated in words
 * somewhere. Entries only appear if that kind of bird is actually on screen.
 */
function drawColorKey(data) {
  const shown = data.species.filter(
    (s) => s.shift_days !== null && s.reliability !== 'excluded'
  );
  const entries = [
    ['--series-migrant', 'migratory warbler',
      shown.some((s) => !s.is_control && s.reliability !== 'flagged')],
    ['--series-flagged', 'warbler that also winters here, read with care',
      shown.some((s) => !s.is_control && s.reliability === 'flagged')],
    ['--series-control', 'resident control bird, cannot migrate',
      shown.some((s) => s.is_control)],
  ];

  const list = document.getElementById('color-key');
  list.innerHTML = '';
  for (const [token, label, present] of entries) {
    if (!present) continue;
    const item = document.createElement('li');
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = cssColor(token);
    item.append(swatch, document.createTextNode(label));
    list.append(item);
  }
}

/**
 * Name the species that were dropped, and say why.
 *
 * A species vanishing from a chart with no explanation is how a reader loses
 * trust in it. If we threw a bird out, the page says so.
 */
function drawExclusions(data) {
  const dropped = data.species.filter((s) => s.reliability === 'excluded');
  const box = document.getElementById('excluded-note');
  if (!dropped.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = '';
  const intro = document.createElement('p');
  intro.className = 'footnote';
  intro.textContent =
    dropped.length === 1
      ? 'One species is not on this chart:'
      : `${dropped.length} species are not on this chart:`;
  box.append(intro);

  const list = document.createElement('ul');
  list.className = 'excluded-list';
  for (const s of dropped) {
    const item = document.createElement('li');
    const name = document.createElement('strong');
    name.textContent = s.common_name;
    item.append(name, document.createTextNode(' \u2014 ' + (s.reliability_note || 'excluded')));
    list.append(item);
  }
  box.append(list);
}

/**
 * Fill in the three control numbers: warbler shift, control shift, remainder.
 *
 * Deliberately not a chart. Three values whose whole meaning is one
 * subtraction read better as three numbers and a sentence than as any plot.
 */
function drawControlPanel(data) {
  const warblerShifts = migrants(data).map((s) => s.shift_days);
  const controlShifts = controls(data).map((s) => s.shift_days);
  const panel = document.getElementById('control-panel');

  if (!warblerShifts.length || !controlShifts.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  const warblerMedian = Math.round(median(warblerShifts));
  const controlMedian = Math.round(median(controlShifts));
  const leftOver = warblerMedian - controlMedian;

  document.getElementById('stat-warblers').textContent = formatShift(warblerMedian);
  document.getElementById('stat-controls').textContent = formatShift(controlMedian);
  document.getElementById('stat-net').textContent = formatShift(leftOver);

  let verdict;
  if (Math.abs(controlMedian) < 1) {
    verdict =
      'The residents barely moved, which is the result you want from a control: ' +
      'it means the method is not manufacturing a shift on its own, and the ' +
      'warbler numbers can be read close to face value.';
  } else if (Math.abs(leftOver) <= Math.abs(controlMedian)) {
    verdict =
      `The residents shifted ${formatShift(controlMedian)} by this same method, ` +
      'and they cannot have shifted at all. That is most of what the warblers ' +
      'show. What survives the correction is smaller than the error bar the ' +
      'controls just measured, so the honest reading is that this method cannot ' +
      'detect a real change in these birds over these fifteen years.';
  } else if (Math.abs(controlMedian) >= Math.abs(warblerMedian)) {
    verdict =
      'The residents moved as much as the warblers did. Since they cannot have ' +
      'changed their arrival date, that is a warning: most or all of what this ' +
      'page shows may be a change in who is birdwatching, not in the birds.';
  } else {
    verdict =
      `The residents moved ${formatShift(controlMedian)}, and they cannot have. ` +
      'That much of every warbler number is drift in the measurement, which is ' +
      'why the figure that matters is the one on the right.';
  }
  document.getElementById('control-verdict').textContent = verdict;
}

// ---------------------------------------------------------------------------
// Species detail
// ---------------------------------------------------------------------------

// Chart.js instances have to be destroyed before the canvas is reused, or the
// old chart keeps handling mouse events over the new one.
let detailChart = null;

/**
 * Draw one species' ten individual springs.
 *
 * Why this view exists: a shift of "7 days earlier" can be a steady slide
 * across fifteen years, or four unremarkable springs and one very odd one.
 * Those mean different things, and the single number cannot tell them apart.
 *
 * The two windows are drawn as two segments of one line with a real gap
 * between them. Joining 2012 to 2020 with a straight line would draw eight
 * years we never measured.
 */
function drawDetail(data, speciesRow) {
  document.getElementById('detail-name').innerHTML =
    `${speciesRow.common_name} <em>${speciesRow.scientific_name}</em>`;
  document.getElementById('detail-note').textContent =
    speciesRow.reliability_note || '';

  const years = speciesRow.yearly.map((y) => y.year);
  const earlyYears = new Set(
    range(data.windows.early[0], data.windows.early[1])
  );

  // One dataset per window, each null outside its own years, so the line
  // breaks where the data does.
  const seriesFor = (inWindow) =>
    speciesRow.yearly.map((y) =>
      inWindow(y.year) && y.used ? y.arrival_doy : null
    );

  const color = speciesRow.is_control
    ? cssColor('--series-control')
    : cssColor('--series-migrant');

  if (detailChart) detailChart.destroy();

  detailChart = new Chart(document.getElementById('detail-chart'), {
    type: 'line',
    data: {
      labels: years,
      datasets: [
        {
          label: 'arrival date',
          data: seriesFor((y) => earlyYears.has(y)),
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 7,
          spanGaps: false,
          tension: 0,
        },
        {
          label: 'arrival date (late window)',
          data: seriesFor((y) => !earlyYears.has(y)),
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 7,
          spanGaps: false,
          tension: 0,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: {
          title: { display: true, text: 'arrival date', color: cssColor('--text-muted') },
          ticks: {
            color: cssColor('--text-secondary'),
            precision: 0,
            callback: (v) => (Number.isInteger(v) ? formatDay(v) : null),
          },
          grid: { color: cssColor('--grid'), drawTicks: false },
          border: { color: cssColor('--border') },
        },
        x: {
          ticks: { color: cssColor('--text-secondary') },
          grid: { display: false },
          border: { color: cssColor('--border') },
        },
      },
      plugins: {
        // One measure, one colour, and the heading already names the bird,
        // so a legend box would only add furniture.
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const row = speciesRow.yearly[item.dataIndex];
              if (row.arrival_doy === null) return 'not enough sightings';
              return `${formatDay(row.arrival_doy)} \u00b7 ${row.n.toLocaleString()} sightings`;
            },
          },
        },
      },
    },
  });

  drawDetailTable(speciesRow);
}

/** Inclusive integer range, e.g. range(2008, 2012). */
function range(from, to) {
  const out = [];
  for (let n = from; n <= to; n++) out.push(n);
  return out;
}

/** The same yearly numbers as a table, including the sightings count. */
function drawDetailTable(speciesRow) {
  const body = document.querySelector('#detail-table tbody');
  body.innerHTML = '';
  for (const year of speciesRow.yearly) {
    const tr = document.createElement('tr');
    if (!year.used) tr.className = 'skipped';
    const cells = [
      String(year.year),
      year.arrival_doy === null ? '\u2014' : formatDay(year.arrival_doy),
      year.n.toLocaleString(),
      year.used ? 'yes' : 'too few',
    ];
    cells.forEach((text, i) => {
      const cell = document.createElement(i === 0 ? 'th' : 'td');
      if (i === 0) cell.scope = 'row';
      cell.textContent = text;
      tr.append(cell);
    });
    body.append(tr);
  }
}

/**
 * Build the row of species buttons and wire up selection.
 *
 * Real buttons rather than clickable canvas regions, so the detail view can
 * be reached with a keyboard and read by a screen reader. Clicking the main
 * chart is added on top of this, not instead of it.
 */
function buildSpeciesChips(data) {
  const row = document.getElementById('species-chips');
  row.innerHTML = '';

  const select = (speciesRow) => {
    for (const chip of row.children) {
      chip.setAttribute('aria-selected', String(chip.dataset.name === speciesRow.common_name));
    }
    drawDetail(data, speciesRow);
  };

  for (const speciesRow of data.species) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip' + (speciesRow.is_control ? ' chip-control' : '');
    chip.textContent = speciesRow.common_name;
    chip.dataset.name = speciesRow.common_name;
    chip.setAttribute('role', 'tab');
    chip.setAttribute('aria-selected', 'false');
    chip.addEventListener('click', () => select(speciesRow));
    row.append(chip);
  }

  document.getElementById('detail-panel').hidden = false;
  select(data.species[0]);
  return select;
}

// ---------------------------------------------------------------------------
// Start here
// ---------------------------------------------------------------------------

function render(data) {
  document.getElementById('generated-at').textContent = data.generated_at
    ? `Data generated ${data.generated_at}.`
    : 'No pipeline run yet.';

  if (!data.species.length) {
    document.getElementById('answer').textContent =
      'This page has no results to show yet.';
    document.getElementById('empty-state').hidden = false;
    return;
  }

  const { answer, subhead } = buildAnswer(data);
  document.getElementById('answer').textContent = answer;
  document.getElementById('subhead').textContent = subhead;

  document.getElementById('early-window-label').textContent =
    `${data.windows.early[0]}–${data.windows.early[1]}`;
  document.getElementById('late-window-label').textContent =
    `${data.windows.late[0]}–${data.windows.late[1]}`;

  document.getElementById('main-chart-panel').hidden = false;
  drawMainChart(data);
  drawColorKey(data);
  drawExclusions(data);
  drawControlPanel(data);

  // The chips own the detail view; the main chart just borrows their
  // selection function so a click on a row does the same thing.
  const selectSpecies = buildSpeciesChips(data);
  wireMainChartClicks(data, selectSpecies);
  watchWidth(data, selectSpecies);
}

fetch(DATA_URL)
  .then((response) => {
    if (!response.ok) throw new Error(`could not load ${DATA_URL}: ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    // A visible failure beats a blank page. If the JSON is missing the reader
    // should be told, not left looking at a headline that never loads.
    document.getElementById('answer').textContent =
      'The results file could not be loaded.';
    document.getElementById('subhead').textContent = String(error);
    console.error(error);
  });
