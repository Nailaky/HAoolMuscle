/* Coloration syntaxique et classification des lignes CML (côté navigateur). */
(function () {
  "use strict";

  function esc(s) {
    return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  // Ordre important : chaînes, commentaires, requêtes, K, registres, commandes, nombres.
  const TOKEN_RE = /("[^"]*")|(^\s*\/.*$)|(\?[A-Za-z0-9]*)|([Kk]\d+)|([PSAMTVNRHpsamtvnrh]\d*)(?=[.=,;:+\-\s]|$)|(\^\d*|~|\|\d*|\(|\)|\$|\[L?\d*|\]L?1?|\}|>|<|\*1?|_SKH|_mop|B100|L100|END|\bB\d+|\bL\d+)|(\.\d+)|(-?\d+)|([^\s])/g;

  function highlight(line) {
    let out = "";
    let m;
    TOKEN_RE.lastIndex = 0;
    while ((m = TOKEN_RE.exec(line)) !== null) {
      const text = esc(m[0]);
      if (m[1]) out += `<span class="tok-str">${text}</span>`;
      else if (m[2]) out += `<span class="tok-comment">${text}</span>`;
      else if (m[3]) out += `<span class="tok-query">${text}</span>`;
      else if (m[4]) out += `<span class="tok-k">${text}</span>`;
      else if (m[5]) out += `<span class="tok-reg">${text}</span>`;
      else if (m[6]) out += `<span class="tok-cmd">${text}</span>`;
      else if (m[7]) out += `<span class="tok-id">${text}</span>`;
      else if (m[8]) out += `<span class="tok-num">${text}</span>`;
      else out += text;
      if (m[0].length === 0) TOKEN_RE.lastIndex++;
    }
    return out;
  }

  const READ_ONLY_RE = /^\s*(\?[A-Za-z0-9]*(\.\d+)?|[PSAMTVNRHK]\d+(\.\d+)?|_SKH(\.\d+)?|\*1?(\.\d+)?)\s*$/i;
  function isReadOnly(line) {
    const parts = line.split(",").filter((p) => p.trim());
    return parts.length > 0 && parts.every((p) => READ_ONLY_RE.test(p));
  }

  /* Décrit une ligne à partir de la référence (commandes, requêtes, K) pour la confirmation. */
  function describe(line, ref) {
    const parts = line.split(",").map((p) => p.trim()).filter(Boolean);
    const infos = [];
    for (const p of parts) {
      const body = p.replace(/\.\d+(?=\s*=|[+\-]?$)/, "");  // retire le suffixe .id (K37.1=10, P4.1+, ^.1)
      let m;
      if ((m = /^K(\d+)\s*=\s*(-?\d+)$/i.exec(body))) {
        const k = ref.parametres_k.find((x) => x.k === Number(m[1]));
        infos.push({ danger: "configuration", nom: k ? `K${k.k} — ${k.nom}` : `K${m[1]} (inconnu)`, warn: k && k.avertissement, k, valeur: Number(m[2]) });
      } else if ((m = /^([PSAMTVNRH])(\d+)\s*=/i.exec(body))) {
        const fam = ref.registres.find((x) => x.lettre === m[1].toUpperCase());
        infos.push({ danger: "configuration", nom: `écriture du registre ${m[1].toUpperCase()}${m[2]}${fam ? " (" + fam.nom + ")" : ""}` });
      } else if (/^\?/.test(body) || /^[PSAMTVNRHK]\d+$/i.test(body) || body === "_SKH") {
        infos.push({ danger: "lecture", nom: "lecture" });
      } else {
        const key = body.replace(/\d+$/, (d) => (/^[\^\|\[]/.test(body) ? (body.startsWith("[L") ? "n" : "n") : d));
        let cmd = ref.commandes.find((c) => c.cmd === body) ||
          ref.commandes.find((c) => c.cmd === key) ||
          ref.commandes.find((c) => c.cmd === body[0] + "#" ) ||
          ref.commandes.find((c) => c.cmd === body[0] + "n");
        if (/^\^\d+$/.test(body)) cmd = ref.commandes.find((c) => c.cmd === "^n");
        if (/^\|\d+$/.test(body)) cmd = ref.commandes.find((c) => c.cmd === "|" + body.slice(1));
        if (/^\[L\d+$/.test(body)) cmd = ref.commandes.find((c) => c.cmd === "[Ln");
        else if (/^\[\d+$/.test(body)) cmd = ref.commandes.find((c) => c.cmd === "[n");
        if (/^[OF]\d$/.test(body)) cmd = ref.commandes.find((c) => c.cmd === body[0] + "#");
        if (/^_SKH=/.test(body)) cmd = ref.commandes.find((c) => c.cmd === "_SKH");
        if (/^_mop=/i.test(body)) cmd = ref.commandes.find((c) => c.cmd === "_mop=");
        if (/^[BL]\d+$/i.test(body)) infos.push({ danger: "memoire", nom: "début de banque (les lignes suivantes seront enregistrées dans le moteur)" });
        else if (/^END$/i.test(body)) infos.push({ danger: "memoire", nom: "fin de banque" });
        else infos.push({ danger: cmd ? cmd.danger : "inconnu", nom: cmd ? `${cmd.cmd} — ${cmd.nom}` : `instruction inconnue : ${body}`, note: cmd && cmd.note });
      }
    }
    return infos;
  }

  window.CML = { highlight, isReadOnly, describe, esc };
})();
