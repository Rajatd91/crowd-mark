/* The companies covered, and the markets that price each one.

   Every slug is a real Polymarket event. A company is only listed here if a
   market asks what it is worth, not merely whether something happens to it.
   Search on the site finds markets for any other company.
*/
export const COMPANIES = [
  {
    id: "anthropic", name: "Anthropic", sector: "AI research",
    kind: "ipo",
    timing: "anthropic-ipo-by",
    caps: [
      "anthropic-ipo-closing-market-cap-higher-strikes",
      "what-will-anthropics-ipo-valuation-be",
      "anthropic-ipo-closing-market-cap-119",
    ],
  },
  {
    id: "openai", name: "OpenAI", sector: "AI research",
    kind: "ipo",
    timing: "openai-ipo-by",
    caps: [
      "what-will-openais-ipo-valuation-be",
      "openai-ipo-closing-market-cap-554",
    ],
  },
  {
    id: "anduril", name: "Anduril", sector: "Defence technology",
    kind: "round",
    ladder: "will-andurils-valuation-hit-by-december-31",
  },
  {
    id: "neuralink", name: "Neuralink", sector: "Neurotechnology",
    kind: "round",
    ladder: "will-neuralinks-valuation-hit-by-december-31",
  },
];

export const slugsFor = c => [c.timing, ...(c.caps || []), c.ladder].filter(Boolean);
export const allSlugs = () => [...new Set(COMPANIES.flatMap(slugsFor))];
export const byId = id => COMPANIES.find(c => c.id === id);
