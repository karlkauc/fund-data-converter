import { tokenizeXml } from "../src/lib/xmlHighlight";

const join = (s: string) => tokenizeXml(s).map((t) => t.text).join("");
const kinds = (s: string) => tokenizeXml(s).map((t) => `${t.kind}:${t.text}`);

test("elements, attributes and text", () => {
  expect(kinds('<Amount ccy="EUR">100</Amount>')).toEqual([
    "punct:<", "tag:Amount", "text: ", "attr:ccy", "eq:=", 'value:"EUR"', "punct:>",
    "text:100", "punct:</", "tag:Amount", "punct:>",
  ]);
});

test("declaration, comment, CDATA, self-closing tag and entities", () => {
  const src = `<?xml version='1.0'?>\n<!-- c --><a><![CDATA[x<y]]><b/>&amp;</a>`;
  const k = tokenizeXml(src);
  expect(k[0]).toEqual({ kind: "decl", text: "<?xml version='1.0'?>" });
  expect(k).toContainEqual({ kind: "comment", text: "<!-- c -->" });
  expect(k).toContainEqual({ kind: "cdata", text: "<![CDATA[x<y]]>" });
  expect(k).toContainEqual({ kind: "punct", text: "/>" });
  expect(k).toContainEqual({ kind: "text", text: "&amp;" });
  expect(join(src)).toBe(src);
});

test("namespaced attributes and > inside values", () => {
  const src = '<FundsXML4 xmlns:xsi="http://x" xsi:noNamespaceSchemaLocation="a>b.xsd">';
  expect(kinds(src)).toContain("attr:xsi:noNamespaceSchemaLocation");
  expect(kinds(src)).toContain('value:"a>b.xsd"');
  expect(join(src)).toBe(src);
});

test("truncated input is kept as text", () => {
  for (const src of ['<a><Amount ccy="EU', "<a><!-- open", "<a><![CDATA[x", "<", "<?xml"]) {
    expect(join(src)).toBe(src);
  }
  expect(tokenizeXml('<a><Amount ccy="EU').at(-1)).toEqual({ kind: "text", text: '<Amount ccy="EU' });
});

test("empty input", () => {
  expect(tokenizeXml("")).toEqual([]);
});
