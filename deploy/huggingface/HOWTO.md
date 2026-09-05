# Putting the API on Hugging Face Spaces

Free, no card, and it takes a Dockerfile.

1. huggingface.co → sign up → **New Space**
2. Name `reversa-api`, SDK **Docker**, **Blank** template, visibility **Public**
3. Clone the Space, copy three things into it, push:

       cp Dockerfile.hf              <space>/Dockerfile
       cp -r backend                 <space>/backend
       cp deploy/huggingface/README.md <space>/README.md

   The frontmatter in that README is not decoration - `app_port: 7860` is how
   Spaces knows where to route, and `sdk: docker` is how it knows to build at
   all.

4. Space → **Settings → Variables and secrets**:

       REVERSA_CORS_ORIGINS = https://reversa-ai.vercel.app

   Optional: `REVERSA_ANTHROPIC_API_KEY` as a **secret**, not a variable, so it
   is not readable from the Space page. Without it the investigation agent runs
   its deterministic path.

5. First build takes 5-10 minutes. It installs scipy and scikit-learn and seeds
   300k payments. It is not stuck.

The URL will be `https://<user>-reversa-api.hf.space`. Send it over and the
frontend gets pointed at it.
