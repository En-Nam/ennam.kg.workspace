// Renders every <pre class="mermaid"> into an SVG with the pack's theme.
// Loaded by each document (after mermaid.min.js), so the HTML renders diagrams when opened
// directly in a browser and render.mjs prints exactly what the browser shows.
// Sets window.__diagramsDone = true and window.__diagramErrors = [...] when finished.
(async () => {
  window.__diagramErrors = [];
  try {
    const css = getComputedStyle(document.body);
    const v = (name) => css.getPropertyValue(name).trim();
    const b50 = v('--b-50'), b100 = v('--b-100'), b300 = v('--b-300'), b600 = v('--b-600'),
          b700 = v('--b-700'), b800 = v('--b-800'), acc = v('--accent'), acc50 = v('--accent-50'),
          acc100 = v('--accent-100'), ink = v('--ink');
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      securityLevel: 'loose',
      fontFamily: '"Be Vietnam Pro", "Helvetica Neue", Arial, sans-serif',
      themeVariables: {
        fontSize: '14px',
        primaryColor: b50, primaryBorderColor: b600, primaryTextColor: ink,
        secondaryColor: acc50, secondaryBorderColor: acc, tertiaryColor: '#ffffff',
        lineColor: b600, textColor: ink,
        clusterBkg: acc50, clusterBorder: acc100,
        edgeLabelBackground: '#ffffff',
        nodeBorder: b600, mainBkg: b50,
        // sequence diagrams
        actorBkg: b700, actorBorder: b800, actorTextColor: '#ffffff', actorLineColor: b300,
        signalColor: b800, signalTextColor: ink, labelBoxBkgColor: acc50, labelBoxBorderColor: acc,
        labelTextColor: ink, loopTextColor: b800, activationBkgColor: acc100, activationBorderColor: acc,
        sequenceNumberColor: '#ffffff',
        noteBkgColor: '#fff6e0', noteBorderColor: '#e6b34d', noteTextColor: ink,
        // state / ER
        altBackground: b50, attributeBackgroundColorOdd: '#ffffff', attributeBackgroundColorEven: b50,
        // xychart
        xyChart: { plotColorPalette: b600 },
      },
      flowchart: { htmlLabels: true, curve: 'basis', useMaxWidth: false, padding: 12 },
      sequence: { useMaxWidth: false, mirrorActors: false },
      er: { useMaxWidth: false },
      state: { useMaxWidth: false },
      xyChart: { useMaxWidth: false },
    });
    // Label boxes are sized from font metrics at render time, so the font must be loaded first.
    // Google Fonts splits the family into unicode-range subsets; the probe text must include
    // Vietnamese glyphs or only the Latin subset loads and labels are measured with a fallback.
    const probe = 'AaĐđ ếềểễệ ạặầẩậ ữựừửứ ọộổỗơờởợ ịỉ ỳỹ';
    await Promise.all(['300', '400', '600', '700'].map((w) =>
      document.fonts.load(`${w} 14px "Be Vietnam Pro"`, probe)));
    const nodes = [...document.querySelectorAll('pre.mermaid')];
    for (const [i, el] of nodes.entries()) {
      try {
        const { svg } = await mermaid.render('m' + i, el.textContent);
        const div = document.createElement('div');
        div.className = 'diagram';
        div.innerHTML = svg; // mermaid's own SVG output from our own static source
        el.replaceWith(div);
      } catch (e) {
        window.__diagramErrors.push(`#${i}: ${e.message}`);
        console.error('Mermaid diagram', i, e);
      }
    }
    await document.fonts.ready;
    // Effective print size of 14px diagram labels once the SVG is scaled into its figure box.
    window.__diagramScales = [...document.querySelectorAll('.diagram svg')].map((svg, i) => {
      const vb = svg.viewBox.baseVal;
      const nw = vb && vb.width ? vb.width : svg.getBBox().width;
      const nh = vb && vb.height ? vb.height : svg.getBBox().height;
      const box = svg.getBoundingClientRect();
      // A height cap letterboxes the drawing, so the effective scale is the smaller of the two.
      const scale = Math.min(box.width / nw, box.height / nh);
      const cap = svg.closest('.figure')?.querySelector('.cap')?.textContent.trim().slice(0, 40) ?? `#${i}`;
      return { cap, pt: +(14 * 0.75 * scale).toFixed(1) };
    });
  } catch (e) {
    window.__diagramErrors.push(`init: ${e.message}`);
    console.error(e);
  } finally {
    window.__diagramsDone = true;
  }
})();
