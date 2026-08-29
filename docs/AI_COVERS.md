# AI covers and illustrations

Generation providers are disabled by default and injected behind provider protocols. No credentials or publisher-specific implementation is hard-coded. An explicitly approved service can be connected with `WEBNOVEL_AI_IMAGE_PROVIDER=http`, `WEBNOVEL_AI_IMAGE_ENDPOINT`, and `WEBNOVEL_AI_IMAGE_API_KEY`; production endpoints must use HTTPS. The adapter sends a grounded JSON brief and accepts raw image bytes, while credentials are never stored in prompt metadata. Cover briefs use title, author, genre, setting, period, themes, and a spoiler-free description, with explicit constraints against copied covers, adaptation art, commercial artwork, or imitation of living artists.

The cover service creates portrait (1200×1800), thumbnail (400×600), and OpenGraph (1200×630) WebP variants under `storage/covers/<slug>`. It stores hashes, dimensions, MIME type, brief metadata, and approval state. Generated images enter an admin approval queue; publication requires all three approved variants. Reusing an approved cover is preferred to regeneration.

Chapter illustrations are optional. Supported modes are none, important chapters, every 5, every 10, AI-selected, or all chapters; the initial default is none. Outputs are resized WebP files under `storage/chapter-images` and remain unapproved until reviewed. Prompts are grounded in a canonical excerpt and chapter hash, but images never replace or alter source prose.

Rollout is 20 covers, then 100, then 1,000, then the remaining approved catalogue. A real provider, credentials, cost limits, safety filters, retry policy, and rights review must be explicitly configured before generation starts.
