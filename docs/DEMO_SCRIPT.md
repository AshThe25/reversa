# Demo script

Five minutes. The order matters more than the words: the argument only lands if
the uncomfortable number arrives before the impressive one.

Have running before you start:

- the API (deployed, or `cd backend && python -m uvicorn reversa.main:app`)
- the app at https://reversa-ai.vercel.app
- one browser tab, nothing else visible
- your Razorpay test dashboard open on Payment Links, in a second tab

Sign in as guest first so no credential appears on camera.

---

## 0:00 - 0:35 · The problem, before the product

**On screen:** the landing page.

> "When an online payment fails, some of that money comes back on its own. The
> customer retries. The bank recovers. The card works an hour later.
>
> Every recovery tool sends an SMS or a payment link, and then counts everything
> that arrives as money it recovered.
>
> Most of it was arriving anyway."

Point at the three figures in the hero.

> "This merchant is told they recovered seven lakh twenty-four thousand. Five
> ninety-nine of that was coming back without anyone doing anything. The real
> number is one twenty-six."

Do not explain the method yet. Let the gap sit.

---

## 0:35 - 1:15 · It finds the break itself

**Click:** Skip to the console.

> "This is today's payment stream. Twenty lakh at risk across eighteen thousand
> declined authorisations."

**Click:** Incidents.

> "It watches success rates per slice and flags the ones that broke against
> their own baseline. Four incidents today. One PSP outage takes down every UPI
> handle at once - that's one incident here, not seven alerts."

---

## 1:15 - 2:00 · The agent, and the part it refuses

**Click:** Investigate on the UPI incident.

> "The agent gets a set of questions it can ask about this incident and writes
> its own queries. Here it asked three - is the drop real, does it cross
> methods, does it cross instruments - and then stopped."

Point at the skipped list.

> "It didn't ask the other three. A method-wide degradation is upstream of any
> single bank, so nothing left could change the answer. What it declined to ask
> is on the record next to what it asked."

If you have time, open the `*/*` incident.

> "On this one it refuses. Insufficient evidence. It will not name a cause the
> evidence can't carry."

---

## 2:00 - 2:50 · The whole argument, on one screen

**Click:** Futures → Run analysis.

> "Before contacting anyone, it replays the incident against every strategy on
> the same customers."

Point at the three figures on the left.

> "Thirty lakh exposed. Eighteen point four six would come back with no
> treatment at all - that line says it: *a conventional tool books this as
> recovered*. Eleven sixty is the only part worth touching."

Point at the bars.

> "And the most aggressive strategy isn't the best one. Payment-link-everyone
> costs more and adds less than the constrained optimum."

---

## 2:50 - 3:30 · Where the money goes, and who a human sees

**Click:** Portfolio.

> "Capacity is finite - twenty-four payment links, because that's under
> Razorpay test mode's ceiling. So it ranks by what a treatment would actually
> add."

Point at a high-baseline row.

> "This twenty-four thousand rupee payment was eighty-three percent likely to
> recover on its own. Chasing it earns a hundred and sixty-four rupees. A
> smaller one that was never coming back earns six thousand eight hundred."

Scroll to the review panel.

> "Four of these forty decisions need a person - anything a customer sees,
> anything over the threshold. The other thirty-six are silent gateway retries
> nobody notices, and it says why each one didn't need a human."

---

## 3:30 - 4:15 · The number is measured, not claimed

**Click:** Tests.

> "A randomly chosen slice of the plan was deliberately left untreated. Whatever
> that group recovers is what the treated group would have recovered anyway."

Point at the badge.

> "One point two six lakh of lift - and it prints *revenue lift not
> significant* next to its own headline number, because the interval crosses
> zero. It will not oversell itself."

**Click:** Eval.

> "And it's graded against an answer key it is never allowed to read. Seventy-five
> percent recall. It names the incident it missed - a single bank at two percent
> of traffic."

---

## 4:15 - 4:45 · It's real

**Switch tabs:** Razorpay dashboard, Payment Links.

> "This isn't simulated end to end. That's a real Payment Link created through
> the Razorpay API from this system."

**Back to the app:** Command → System panel.

> "The service reports which mode every adapter is in. Razorpay test mode, live
> calls counted. A key starting rzp underscore live is refused at startup - no
> override."

---

## 4:45 - 5:00 · Close

> "Every recovery tool tells you how much money came back. This one tells you
> how much came back *because of you* - and spends only on that."

---

## If you have thirty seconds spare

Audit page: click a row, show the hash chain. "Every decision commits to the one
before it."

## Things to avoid

- Don't say "simulation" while the Razorpay dashboard is on screen; it undercuts
  the one moment that proves it isn't.
- Don't apologise for the 75% recall. Reporting it is the point.
- Don't read the statistics vocabulary aloud. "Corrected for testing hundreds of
  slices at once" beats "Benjamini-Hochberg" for every audience that matters.
