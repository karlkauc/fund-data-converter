/**
 * Minimal XML tokenizer for syntax highlighting the FundsXML preview.
 *
 * Linear, regex-free outside of tags, and tolerant of input cut off anywhere
 * (the preview is the first ~60 KB of the document): an unfinished construct
 * at the end becomes a ``text`` token. The tokens always concatenate back to
 * the exact input.
 */

export type TokenKind = "punct" | "tag" | "attr" | "eq" | "value" | "text" | "comment" | "decl" | "cdata";

export interface Token {
  kind: TokenKind;
  text: string;
}

// Inside a tag: whitespace, attribute name, "=", quoted value, or anything else (one char).
const IN_TAG = /(\s+)|([^\s=/>"']+)|(=)|("[^"]*"|'[^']*')|([\s\S])/y;

export function tokenizeXml(src: string): Token[] {
  const out: Token[] = [];
  const push = (kind: TokenKind, text: string) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.kind === kind && kind === "text") last.text += text;
    else out.push({ kind, text });
  };

  let i = 0;
  const n = src.length;
  while (i < n) {
    const lt = src.indexOf("<", i);
    if (lt === -1) {
      push("text", src.slice(i));
      break;
    }
    if (lt > i) push("text", src.slice(i, lt));
    i = lt;

    const block = (open: string, close: string, kind: TokenKind): boolean => {
      if (!src.startsWith(open, i)) return false;
      const end = src.indexOf(close, i + open.length);
      if (end === -1) {
        push("text", src.slice(i));
        i = n;
      } else {
        push(kind, src.slice(i, end + close.length));
        i = end + close.length;
      }
      return true;
    };
    if (block("<!--", "-->", "comment") || block("<![CDATA[", "]]>", "cdata") || block("<?", "?>", "decl")) {
      continue;
    }
    if (src.startsWith("<!", i)) {
      // DOCTYPE and similar: not produced by the converter, shown as a declaration.
      if (!block("<!", ">", "decl")) i++;
      continue;
    }

    // Start, end or empty-element tag. Find its end first; unfinished → plain text.
    const end = findTagEnd(src, i);
    if (end === -1) {
      push("text", src.slice(i));
      break;
    }
    const open = src.startsWith("</", i) ? "</" : "<";
    push("punct", open);
    let j = i + open.length;
    const nameMatch = /[^\s/>]+/y;
    nameMatch.lastIndex = j;
    const name = nameMatch.exec(src);
    if (name && name.index === j) {
      push("tag", name[0]);
      j += name[0].length;
    }
    const closeLen = src[end - 1] === "/" ? 2 : 1;
    const bodyEnd = end + 1 - closeLen;
    let expectName = true;
    IN_TAG.lastIndex = j;
    while (IN_TAG.lastIndex < bodyEnd) {
      const m = IN_TAG.exec(src);
      if (!m) break;
      let text = m[0];
      if (m.index + text.length > bodyEnd) text = src.slice(m.index, bodyEnd);
      if (m[1]) push("text", text);
      else if (m[2]) {
        push(expectName ? "attr" : "value", text);
        expectName = true;
      } else if (m[3]) {
        push("eq", text);
        expectName = false;
      } else if (m[4]) {
        push("value", text);
        expectName = true;
      } else push("punct", text);
      IN_TAG.lastIndex = m.index + text.length;
    }
    push("punct", src.slice(bodyEnd, end + 1));
    i = end + 1;
  }
  return out;
}

/** Index of the ">" that closes the tag starting at ``start`` (quotes respected), or -1. */
function findTagEnd(src: string, start: number): number {
  let quote = "";
  for (let k = start + 1; k < src.length; k++) {
    const c = src[k];
    if (quote) {
      if (c === quote) quote = "";
    } else if (c === '"' || c === "'") quote = c;
    else if (c === ">") return k;
    else if (c === "<") return -1;
  }
  return -1;
}
