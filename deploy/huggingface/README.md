---
title: Reversa API
emoji: 📉
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Reversa API

Counterfactual revenue recovery for failed payments. This Space runs the API
only — the interface lives at https://reversa-ai.vercel.app and calls this.

Source: https://github.com/AshThe25/reversa

The world is seeded into the image at build time, so the numbers are the same
ones the repository's test suite is pinned against. No Razorpay credentials are
configured here and none are needed: the adapter runs in simulation, and a
`rzp_live_` key is refused at startup regardless.
