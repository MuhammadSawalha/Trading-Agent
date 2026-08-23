// Guided question builder for ChatPanel: topic -> specific question -> stock(s).
// Every question here is grounded in a field the pipeline actually produces
// (see services/scheduler/src/graph/{specialists,debate,risk,manager}.py and
// services/mcp-server/src/tools/scoring.py) so the chat, which only reads cached
// AgentOutputs, can genuinely answer it.

export type ChatSubtopic = {
  id: string;
  label: string;
  need: number;
  skipSymbol?: boolean;
  question: (symbols: string[]) => string;
};

export type ChatCategory = {
  id: string;
  label: string;
  need?: number;
  skipSubtopic?: boolean;
  question?: (symbols: string[]) => string;
  subtopics?: ChatSubtopic[];
};

export const CHAT_CATEGORIES: ChatCategory[] = [
  {
    id: "overview",
    label: "Composite score / overview",
    subtopics: [
      { id: "score", label: "Current composite score", need: 1, question: (s) => `What's the current composite score for ${s[0]}?` },
      { id: "breakdown", label: "Score breakdown by specialist", need: 1, question: (s) => `Break down ${s[0]}'s composite score by specialist.` },
      { id: "confidence", label: "How confident is this score?", need: 1, question: (s) => `How confident is ${s[0]}'s composite score?` },
    ],
  },
  {
    id: "bullbear",
    label: "Bull vs. Bear case",
    subtopics: [
      { id: "bull", label: "Bull case", need: 1, question: (s) => `What's the bull case for ${s[0]}?` },
      { id: "bear", label: "Bear case", need: 1, question: (s) => `What's the bear case for ${s[0]}?` },
      { id: "bullrebutted", label: "Which bull claims did the bear rebut?", need: 1, question: (s) => `Which of ${s[0]}'s bull claims did the bear rebut?` },
      { id: "strongest", label: "Strongest argument each side", need: 1, question: (s) => `What's the single strongest bull and bear argument for ${s[0]}?` },
    ],
  },
  {
    id: "fundamentals",
    label: "Fundamentals",
    subtopics: [
      { id: "valuation", label: "Valuation", need: 1, question: (s) => `How does ${s[0]}'s valuation look?` },
      { id: "margins", label: "Margins & profitability", need: 1, question: (s) => `How are ${s[0]}'s margins and profitability trending?` },
      { id: "insider", label: "Insider activity", need: 1, question: (s) => `Any insider activity flagged for ${s[0]}?` },
      { id: "corroborated", label: "Corroborated vs. weak claims", need: 1, question: (s) => `Which fundamentals claims on ${s[0]} are corroborated vs. weak?` },
    ],
  },
  {
    id: "technicals",
    label: "Technicals",
    subtopics: [
      { id: "trend", label: "Trend & momentum", need: 1, question: (s) => `What's the trend and momentum picture for ${s[0]}?` },
      { id: "volume", label: "Unusual volume", need: 1, question: (s) => `Is there unusual volume on ${s[0]}?` },
      { id: "corroborated", label: "Corroborated signals", need: 1, question: (s) => `Which technical signals on ${s[0]} are corroborated by more than one claim?` },
    ],
  },
  {
    id: "sentiment",
    label: "Sentiment / news",
    subtopics: [
      { id: "overall", label: "Overall sentiment", need: 1, question: (s) => `What's the overall news sentiment on ${s[0]}?` },
      { id: "impactful", label: "Most impactful recent article", need: 1, question: (s) => `What's the most impactful recent article on ${s[0]}?` },
      { id: "primary", label: "Primary coverage vs. mentions", need: 1, question: (s) => `How much of ${s[0]}'s coverage is primary vs. a passing mention?` },
    ],
  },
  {
    id: "macro",
    label: "Macro / options",
    subtopics: [
      { id: "macro", label: "Macro backdrop", need: 1, question: (s) => `What's the macro backdrop for ${s[0]}?` },
      { id: "options", label: "Unusual options activity", need: 1, question: (s) => `Any unusual options activity on ${s[0]}?` },
    ],
  },
  {
    id: "risk",
    label: "Risk",
    subtopics: [
      { id: "top", label: "Top risk factors", need: 1, question: (s) => `What are the top risk factors for ${s[0]}?` },
      { id: "directional", label: "Directional or pure risk read?", need: 1, question: (s) => `Is ${s[0]}'s risk read directional, or pure risk?` },
      { id: "confidenceimpact", label: "How risk affects score confidence", need: 1, question: (s) => `How does risk level affect confidence in ${s[0]}'s score?` },
    ],
  },
  {
    id: "compare",
    label: "Comparisons",
    subtopics: [
      { id: "fundamentals", label: "Compare fundamentals", need: 2, question: (s) => `Compare ${s[0]} and ${s[1]} on fundamentals.` },
      { id: "technicals", label: "Compare technicals", need: 2, question: (s) => `Compare ${s[0]} and ${s[1]} on technicals.` },
      { id: "score", label: "Compare composite scores", need: 2, question: (s) => `Compare ${s[0]} and ${s[1]}'s composite scores.` },
      { id: "risk", label: "Compare risk", need: 2, question: (s) => `Compare risk between ${s[0]} and ${s[1]}.` },
      { id: "full", label: "Full comparison", need: 2, question: (s) => `Give me a full comparison between ${s[0]} and ${s[1]}.` },
    ],
  },
  {
    id: "history",
    label: "History / timing",
    subtopics: [
      { id: "lastupdated", label: "When was it last updated", need: 1, question: (s) => `When was ${s[0]} last updated?` },
      { id: "activity", label: "Recent pipeline activity", need: 1, question: (s) => `What agent runs have happened recently for ${s[0]}, and why?` },
      { id: "timeline", label: "Full process timeline", need: 1, question: (s) => `Show the process-history timeline for ${s[0]}.` },
    ],
  },
  {
    id: "full",
    label: "Full analysis",
    skipSubtopic: true,
    need: 1,
    question: (s) => `Give me the full analysis for ${s[0]}`,
  },
  {
    id: "portfolio",
    label: "Across my watchlist",
    subtopics: [
      { id: "highscore", label: "Highest composite score", need: 0, skipSymbol: true, question: () => `Which stock in my watchlist has the highest composite score?` },
      { id: "highrisk", label: "Highest risk", need: 0, skipSymbol: true, question: () => `Which stock in my watchlist has the highest risk level?` },
      { id: "bullish", label: "Most bullish setup", need: 0, skipSymbol: true, question: () => `Which stock in my watchlist has the strongest bull case right now?` },
      { id: "bearish", label: "Most bearish setup", need: 0, skipSymbol: true, question: () => `Which stock in my watchlist has the strongest bear case right now?` },
      { id: "confidence", label: "Least confident score", need: 0, skipSymbol: true, question: () => `Which stock in my watchlist has the least confident score right now?` },
    ],
  },
];
