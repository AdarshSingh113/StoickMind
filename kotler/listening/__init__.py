"""Social listening: what people say about your brand, your products and your market, outside your own channels.

Every few hours an agent reads public mentions from sources we're ALLOWED to read, labels them, and turns them into
insights and alerts:

  YouTube       comments under public review videos (official Data API, free daily quota, API key)
  Bluesky       public posts (open AT Protocol API, no key)
  Google News   news articles (public RSS search feed, no key)
  Web brief     Gemini with Google Search grounding (cites its sources; needs a paid Gemini key), otherwise
                an AI brief written ONLY from the mentions collected above, with links

Not included, on purpose: scraping LinkedIn, Facebook, Instagram, Amazon or Nykaa. It breaks their terms.
LinkedIn page mentions and Facebook/Instagram page comments need approved API access for a registered business.

Watch terms decide what we look for. "brand" terms are about you (a skin reaction there raises an alert);
"product", "category" and "competitor" terms are market research: real customers talking about vitamin C serums
or a competitor tell you what to fix, stock or say, even before anyone talks about your brand.

Modules: store (tables, terms, retention) · sources (fetchers) · analyze (labels) · insights (numbers, digest,
web brief) · runner (one scan, the schedule, the command line).
"""
