class Coder {
  invoke_coder bool
}

class ResponseToUser {
  response_to_user string
}

template_string  ChatSystemInfo() #"<system_info>
    Keep in mind, this project is an html page that follows best practices.
    Breba app is producing a production ready website that geared towards search engine discoverabilty and core web vitals.
    The website is static in nature, but can use plugin for dynamic functionality.
</system_info>

<limitation>
    When user asks you to do something that you cannot do, tell them.
    1) You cannot view or analyze website urls or any content behind them.
    2) You cannot analyze video or audio.
    3) You cannot analyze PDF files
    </limitation>
"#

function UserResponseOrCoder(messages: LLMMessage[], spec: string, files: string[]) -> ResponseToUser | Coder{
  client Gpt5Low
  prompt #"You are an AI agent within Breba App.
You will talk with user and when appropriate route them to the coder agent (coder).
The user you are talking to is non-technical, avoid using technical jargon unless necessary. The user likely doesn't know anything about code or libraries.
If the request is ambiguous, ask questions.
Ask one question at a time and wait for the answer before asking the next question.
Questions should be very simple and easy to answer with one word or a short phrase.

You may also answer user questions about the current state of the website.

Once you understand the request you MUST either invoke Coder agent or respond to the user with a question or an answer.

IMPORTANT: You ARE NOT WRITING ANY CODE YOURSELF.
IMPORTANT: If something doesn't make sense, ask questions until it does. First address anything that just doesn't make sense.
IMPORTANT: You are the only one who can talk to the user. So ask questions or respond to the user as needed and only after all questions are settled invoke Coder agent.
IMPORTANT: You don't have to ask questions. Ask only if request is ambiguous or too vague.
IMPORTANT: User doesn't know anything about code. For implementation details, defer to coder.



{{ChatSystemInfo()}}

    {{ _.role("system") }}
    {{ ctx.output_format }}

  {% if spec %}
    {{ _.role("user") }}
    I have the following specification for the website:
  {{ spec }}

    {{ _.role("assistant") }}
    Ok. I understand the context of the website.
  {% endif %}

  {% if files %}
    {{ _.role("user") }}
    Here are the files that exist in the project:
    {{ files }}

    {{ _.role("assistant") }}
    Great this helps me understand the state of the project.
  {% endif %}


    {% for message in messages %}
      {{ _.role(message.role) }}
      {% if message.images %}
        {% for image in message.images %}
          {{ image }}
        {% endfor %}
      {% endif %}
      {{ message.content }}
    {% endfor %}

  {{ ctx.output_format }}


  "#
}


function UserResponseOrCoder2(messages: LLMMessage[], spec: string, files: string[]) -> ResponseToUser | Coder{
  client Gpt5Low
  prompt #"You are a website change assistant for a website. 
  Your role is to understand and clarify website change requests from non-technical users before they are passed to a developer.
You have three sources of context: the conversation history, an executive summary of the site, and a stripped representation of the HTML structure showing the site's sections, components, and content.
Your job is to confirm that each request is specific, unambiguous, and actionable before marking it ready for implementation. You are not implementing anything yourself.
When a user submits a request, evaluate it against these criteria:
It is clear what needs to change
It is clear where on the page the change applies
It does not contradict the site's purpose or existing structure
It does not require information or assets not yet provided

If the request meets all criteria, summarize it back to the user in plain language and confirm it is ready to pass on.
If the request is vague or ambiguous, ask one focused question at a time to resolve it. Do not ask multiple questions at once.
Do not explain HTML, CSS, or technical implementation details to the user. Do not suggest how the change will be made. Do not make assumptions about intent — ask instead.


{{ChatSystemInfo()}}

    {{ _.role("system") }}
    {{ ctx.output_format }}

  {% if spec %}
    {{ _.role("user") }}
    I have the following executive summary for the website:
  {{ spec }}

    {{ _.role("assistant") }}
    Ok. I understand the context of the website.
  {% endif %}

  {% if files %}
    {{ _.role("user") }}
    Here are the files that exist in the project:
    {{ files }}
    
    {{ _.role("assistant") }}
    Great this helps me understand the state of the project.
  {% endif %}


    {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.content }}
    {% endfor %}

  {{ ctx.output_format }}


  "#
}


test BuildHelloWorldSite {
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"Build a hello world website for me."#
      }
    ],
    spec "This is a brand new project without a spec",
    files []
  }

}


test BuildHelloWorldSiteNoQuestions {
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"Build a hello world website for me. Do not ask questions"#
      }
    ],
    spec #"This is a brand new project without a spec"#,
    files []
  }
}

test BuildHelloWorldSiteMultiTurn {
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"Build a hello world website for me."#
      },
      {
        role "assistant"
        content #"What is the main purpose of your Hello World website (for example: personal profile, business landing page, or just a simple demo)?""#
      },
      {
        role "user"
        content #"This is a simple demo. It doesn't matter"#
      },
    ],
    spec #"This is a brand new project without a spec"#,
    files []
  }
}


test BuildLandingPage {
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"I would like to build a landing page for my startup."#
      },
      {
        role "assistant"
        content #"What is the name of your startup?"#
      },
      {
        role "user"
        content #"The name of my startup is TechNova."#
      },
      {
        role "assistant"
        content #"What is the main product or service offered by TechNova?"#
      },
      {
        role "user"
        content #"We offer innovative AI solutions for businesses."#
      },
    ],
    spec #""#,
    files []
  }
}

test BuildLandingPageConfusion{
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"Rename Gravel Guard to Gravel Success."#
      },
      {
        role "assistant"
        content #"Got it, you want to rename the brand.\n\nShould we change **every occurrence** of “GravelGuard” to **“Gravel Success”** across the whole site (including title, headings, footer, schema, and form subject), or only the **visible text** on the page?"#
      },
      {
        role "user"
        content #"Everywhere. I'm rebranding"#
      },
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml", "AGENTS.md"]
    spec #"# GravelGuard — Product Specification

## 1. Product Intent

**GravelGuard** is a mobile gravel-road maintenance service focused on **small but critical access roads** (trailheads, rural properties, recreation access) that are underserved by traditional contractors.

The website’s sole job is to:

1. Clearly explain *what problem GravelGuard solves*
2. Establish *credibility and trust*
3. Convert visitors into *qualified inbound leads*

Primary conversion outcome:
**A visitor submits a request for a road assessment**

---

## 2. Target Users & Use Cases

### Primary User Segments

* Public land agencies and counties
* Rural property owners and HOAs
* Outdoor brands, clubs, and trail organizations

### Core Use Cases

* A land manager needs fast repair of a short gravel segment
* A property owner wants predictable access for guests
* An outdoor brand wants to sponsor and visibly support access roads

---

## 3. User Preferences (Non-negotiable)

* Content must feel **field-tested, professional, and practical**
* Tone must avoid:

  * Startup hype
  * “Tech platform” language
  * Playfulness or novelty
* Users prefer:

  * Clear scopes and timelines
  * Plain language explanations
  * Concrete examples (roads, trailheads, miles, days)

---

## 4. Core Invariants (Must Always Hold)

These are *product truths* that must not be violated by design or content changes:

1. **Clarity over cleverness**
   Users should understand the service in under 10 seconds.

2. **Lead capture is primary**
   Every major section must reinforce or support the primary CTA.

3. **Trust before pricing precision**
   Pricing is indicative, flexible, and contextual—not rigid or transactional.

4. **Small-segment specialization**
   GravelGuard is explicitly *not* a general road contractor.

5. **Fast response is a differentiator**
   Assessment and deployment speed is central to the value proposition.

---

## 5. Content Constraints

* Single narrative flow from:
  **Problem → Solution → Proof → Cost → Action**
* One primary call to action:
  **“Request a Road Assessment”**
* Secondary CTAs may exist, but must never compete with the primary CTA.
* All copy must support one of:

  * Understanding
  * Trust
  * Conversion

---

## 6. Information Architecture (Conceptual)

The page is a **single linear experience** composed of these conceptual sections:

1. **Value Proposition**

   * What GravelGuard does
   * Who it’s for
   * Why speed and focus matter

2. **Benefits**

   * Risk reduction (vehicles, guests)
   * Speed and flexibility
   * Fit for agencies and outdoor partners

3. **Process**

   * Simple, low-friction, three-step flow
   * Emphasis on minimal effort from the customer

4. **Social Proof**

   * Testimonials representing each major user segment
   * Realistic language, understated tone

5. **Pricing Orientation**

   * Example tiers to set expectations
   * Clear message: exact pricing requires assessment

6. **Objection Handling**

   * FAQs addressing scope, speed, eligibility, and pricing logic

---

## 7. Conversion Model

### Primary Action

* User submits a road assessment request containing:

  * Contact information
  * Road location
  * Description of issues

### Conversion Principles

* The form must feel:

  * Low effort
  * Non-binding
  * Consultative, not salesy
* Submission feedback must be immediate and reassuring.

---

## 8. Trust Signals (Required)

At least one of each must be present:

* **Operational credibility**

  * Equipment, crews, real-world constraints
* **Social proof**

  * Testimonials from agencies, owners, and sponsors
* **Professional restraint**

  * No exaggerated claims or guarantees beyond stated timelines

---

## 9. SEO & Discoverability (Conceptual)

The product must be clearly associated with:

* Gravel road repair
* Trailhead and recreation access
* Rural and remote access maintenance

SEO is supportive, not the primary UX driver:

* Content must read naturally to humans first.
* Keywords must reinforce meaning, not distort it.

---

## 10. Non-Goals (Explicit Exclusions)

The website is **not** intended to:

* Fully quote or book services
* Educate on road engineering theory
* Serve as a content blog or documentation hub
* Present GravelGuard as a generalized construction firm

---

## 11. Success Criteria

The specification is successful if:

* A first-time visitor understands the service quickly
* The service feels credible without over-explaining
* Users consistently choose to submit the assessment form
* The site attracts qualified, relevant inbound requests
"#
    
  }
}


test BuildLandingPageXMLSpec{
  functions [UserResponseOrCoder]
  args {
    messages [
      {
        role "user"
        content #"Make text green"#
      },
      {
        role "assistant"
        content #"Which text do you want to be green: all text on the website, or just certain parts (for example, headings, prices, or a specific section)?

        "#
      },
      {
        role "user"
        content #"Make all icons green"#
      },
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml", "AGENTS.md"]
    spec #"
  <doc sitename="gravel.breba.site" title="GravelGuard | Fast Gravel Road Repair for Trailheads and Rural Access" url="https://gravel.breba.site" hostname="breba.site" description="GravelGuard provides fast gravel road repair for trailheads, campgrounds, rural driveways, and access roads, fixing potholes, washboards, and drainage issues." tags="gravel road repair, trailhead access, rural driveway maintenance, pothole repair, washboard road, recreation access, road grading, GravelGuard" fingerprint="bc9f4c760db66305">
  <main>
    <head rend="h3">Protect Vehicles and Guests</head>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile Gravel Road Repair</p>
    <p>GravelGuard sends mobile crews to repair potholes, washboards, and drainage failures on remote gravel roads so drivers, hikers, and guests can get through safely.</p>
    <list rend="ul">
      <item>Trailheads, campgrounds, rural driveways, and recreation roads</item>
      <item>Fast-response crews with compact graders and professional equipment</item>
      <item>Flexible options for agencies, landowners, and outdoor sponsors</item>
    </list>
    <p>We focus on the rough, forgotten gravel roads that matter most for trail access, rural living, and outdoor tourism—and we keep them passable without big-contractor complexity.</p>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile crews restore short road segments in 24–72 hours, ideal for trailheads, cabins, Airbnbs, and seasonal spikes.</p>
    <p>Clear scopes, simple pricing, and sponsor options help agencies, clubs, and brands keep key recreation roads open.</p>
    <p>From a rough GPS pin to a smooth, drivable road in a few simple steps.</p>
    <p> 1 Share the Problem </p>
    <p>Send us a map link or GPS pin for the bad road segment, plus a few photos or a brief description.</p>
    <p> 2 Get a Fast Assessment </p>
    <p>We review satellite imagery and your photos, then send a clear scope, estimated timeline, and pricing options.</p>
    <p> 3 Crew Deploys and Repairs </p>
    <p>Our mobile crew arrives with compact graders, water, and aggregate to fix potholes, break washboards, and restore drainage—often in a single day.</p>
    <p> Want ongoing gravel road maintenance instead of one-off fixes? Ask about our seasonal subscriptions for rural driveway maintenance and recreation access roads. </p>
    <p>From rural driveways to busy trailheads, GravelGuard helps keep access open.</p>
    <p>“We had a trailhead road that everyone complained about for years. GravelGuard had it graded, compacted, and draining properly in a day, and the calls stopped.”</p>
    <p>“Our Airbnb guests used to message us about the washboarded driveway. After GravelGuard’s subscription service, reviews mention the ‘easy access’ instead.”</p>
    <p>“Sponsoring a popular trail access road with GravelGuard gave us real impact and great content. We can literally show customers the road we keep open.”</p>
    <p>Every road is different. These example packages help you understand where most projects land. Exact pricing depends on length, condition, and material needs.</p>
    <p>Most Popular</p>
    <p>Starting from $3,000</p>
    <p>For 0.5–3 miles of rough gravel road leading to trailheads, campgrounds, and recreation areas.</p>
    <list rend="ul">
      <item>Pothole filling and washboard removal</item>
      <item>Basic re-crowning and drainage touch-ups</item>
      <item>Before/after documentation for stakeholders</item>
    </list>
    <p>Starting from $2,000 / visit</p>
    <p>Seasonal maintenance for rural driveways, cabins, Airbnbs, small HOAs, and private roads.</p>
    <list rend="ul">
      <item>Scheduled grading every 3–6 months</item>
      <item>Priority response after storms or freeze–thaw damage</item>
      <item>Predictable access for guests and deliveries</item>
    </list>
    <p>Custom contracts</p>
    <p>For land agencies, counties, timber companies, and outdoor brands sponsoring recreation access.</p>
    <list rend="ul">
      <item>Micro-contracts for short segments</item>
      <item>Sponsor-a-Road and co-branded signage</item>
      <item>Emergency response after major events</item>
    </list>
    <p>Need help estimating your road length or condition? We can walk through it over a quick call.</p>
    <p>If you don’t see your question here, include it in your message and we’ll respond directly.</p>
    <p> We focus on gravel and unpaved access roads that serve trailheads, campgrounds, rural homes, cabins, small HOAs, and recreation areas. We’re best suited for short segments that are too small or low-priority for large contractors. </p>
    <p> Most jobs are assessed within 24 hours on business days, and field work is typically scheduled within 24–72 hours after approval, depending on weather, crew availability, and material needs. </p>
    <p> Yes. We regularly partner with forest agencies, BLM and DNR districts, counties, and timber companies to handle small segments, emergency washouts, and recreation-focused roads that don’t fit traditional contracts. </p>
    <p> Absolutely. Our Sponsor-a-Road model lets outdoor brands, breweries, clubs, and donors fund improvements on specific access roads with clear recognition and impact reporting. </p>
    <p> Pricing depends on road length, existing condition, slope and drainage issues, required aggregate, and travel time. Once we review your map location and photos, we provide a clear, no-obligation estimate and scope of work. </p>
    <p> Still unsure if your road is a fit? Send us the location and we’ll let you know. </p>
  </main>
  <comments/>
</doc>
"#
    
  }
}

test BuildLandingPageXMLSpec2{
  functions [UserResponseOrCoder2]
  args {
    messages [
      {
        role "user"
        content #"I just uploaded files:
          image1.png, image2.png, image3.png, image4.png, image5.png, image6.png

          Add images to the corners of hero section
        "#
      }
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml", "SPEC.md"]
    spec #"
      GravelGuard — Executive Summary
Status: Demo/concept only. Not trading, no real customers.
Purpose: Validates market positioning and service framing for a mobile gravel road repair business before a full build-out. The primary conversion signal is inbound assessment requests.
Target audience: A mix of institutional buyers (forest agencies, BLM/DNR, counties) and individual/small-org buyers (rural property owners, Airbnb hosts, HOAs, outdoor brand sponsors). Pricing and messaging serve both without a separate funnel for each.
Geography: Pacific Northwest only. Service area not yet formally defined.
Theme: Dark. No inline styles — all styling via Bootstrap utility classes and custom named classes.
CTAs: Primary — "Request a Road Assessment" (modal contact form). Secondary — "View Pricing" (anchor scroll).
Tech stack: Static HTML/CSS/JS. Bootstrap 5.3.8 from jsDelivr CDN. Google Material Icons from Google Fonts CDN. System font stack — no external font files. Mobile-first responsive layout.
SEO: Fully configured — index, follow, Open Graph, Twitter Card, and LocalBusiness JSON-LD schema.
Analytics: Google Analytics 4, property G-YDY6J4DY62. Actively monitored by the owner.
Integrations: Form submissions route to the owner's email inbox via staticforms.xyz. No CRM in the loop — lead follow-up is manual.
Testimonials: Placeholder. Not from real customers.
Ownership: All accounts (hosting, analytics, form backend, email) held directly by the business owner.
Compliance: No cookie consent banner before GA4 fires. No privacy policy exists. The site is not currently receiving real traffic.
Deployment: Managed via the Breba platform on a breba.site subdomain. No custom domain configured.

  <doc sitename="gravel.breba.site" title="GravelGuard | Fast Gravel Road Repair for Trailheads and Rural Access" url="https://gravel.breba.site" hostname="breba.site" description="GravelGuard provides fast gravel road repair for trailheads, campgrounds, rural driveways, and access roads, fixing potholes, washboards, and drainage issues." tags="gravel road repair, trailhead access, rural driveway maintenance, pothole repair, washboard road, recreation access, road grading, GravelGuard" fingerprint="bc9f4c760db66305">
  <main>
    <head rend="h3">Protect Vehicles and Guests</head>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile Gravel Road Repair</p>
    <p>GravelGuard sends mobile crews to repair potholes, washboards, and drainage failures on remote gravel roads so drivers, hikers, and guests can get through safely.</p>
    <list rend="ul">
      <item>Trailheads, campgrounds, rural driveways, and recreation roads</item>
      <item>Fast-response crews with compact graders and professional equipment</item>
      <item>Flexible options for agencies, landowners, and outdoor sponsors</item>
    </list>
    <p>We focus on the rough, forgotten gravel roads that matter most for trail access, rural living, and outdoor tourism—and we keep them passable without big-contractor complexity.</p>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile crews restore short road segments in 24–72 hours, ideal for trailheads, cabins, Airbnbs, and seasonal spikes.</p>
    <p>Clear scopes, simple pricing, and sponsor options help agencies, clubs, and brands keep key recreation roads open.</p>
    <p>From a rough GPS pin to a smooth, drivable road in a few simple steps.</p>
    <p> 1 Share the Problem </p>
    <p>Send us a map link or GPS pin for the bad road segment, plus a few photos or a brief description.</p>
    <p> 2 Get a Fast Assessment </p>
    <p>We review satellite imagery and your photos, then send a clear scope, estimated timeline, and pricing options.</p>
    <p> 3 Crew Deploys and Repairs </p>
    <p>Our mobile crew arrives with compact graders, water, and aggregate to fix potholes, break washboards, and restore drainage—often in a single day.</p>
    <p> Want ongoing gravel road maintenance instead of one-off fixes? Ask about our seasonal subscriptions for rural driveway maintenance and recreation access roads. </p>
    <p>From rural driveways to busy trailheads, GravelGuard helps keep access open.</p>
    <p>“We had a trailhead road that everyone complained about for years. GravelGuard had it graded, compacted, and draining properly in a day, and the calls stopped.”</p>
    <p>“Our Airbnb guests used to message us about the washboarded driveway. After GravelGuard’s subscription service, reviews mention the ‘easy access’ instead.”</p>
    <p>“Sponsoring a popular trail access road with GravelGuard gave us real impact and great content. We can literally show customers the road we keep open.”</p>
    <p>Every road is different. These example packages help you understand where most projects land. Exact pricing depends on length, condition, and material needs.</p>
    <p>Most Popular</p>
    <p>Starting from $3,000</p>
    <p>For 0.5–3 miles of rough gravel road leading to trailheads, campgrounds, and recreation areas.</p>
    <list rend="ul">
      <item>Pothole filling and washboard removal</item>
      <item>Basic re-crowning and drainage touch-ups</item>
      <item>Before/after documentation for stakeholders</item>
    </list>
    <p>Starting from $2,000 / visit</p>
    <p>Seasonal maintenance for rural driveways, cabins, Airbnbs, small HOAs, and private roads.</p>
    <list rend="ul">
      <item>Scheduled grading every 3–6 months</item>
      <item>Priority response after storms or freeze–thaw damage</item>
      <item>Predictable access for guests and deliveries</item>
    </list>
    <p>Custom contracts</p>
    <p>For land agencies, counties, timber companies, and outdoor brands sponsoring recreation access.</p>
    <list rend="ul">
      <item>Micro-contracts for short segments</item>
      <item>Sponsor-a-Road and co-branded signage</item>
      <item>Emergency response after major events</item>
    </list>
    <p>Need help estimating your road length or condition? We can walk through it over a quick call.</p>
    <p>If you don’t see your question here, include it in your message and we’ll respond directly.</p>
    <p> We focus on gravel and unpaved access roads that serve trailheads, campgrounds, rural homes, cabins, small HOAs, and recreation areas. We’re best suited for short segments that are too small or low-priority for large contractors. </p>
    <p> Most jobs are assessed within 24 hours on business days, and field work is typically scheduled within 24–72 hours after approval, depending on weather, crew availability, and material needs. </p>
    <p> Yes. We regularly partner with forest agencies, BLM and DNR districts, counties, and timber companies to handle small segments, emergency washouts, and recreation-focused roads that don’t fit traditional contracts. </p>
    <p> Absolutely. Our Sponsor-a-Road model lets outdoor brands, breweries, clubs, and donors fund improvements on specific access roads with clear recognition and impact reporting. </p>
    <p> Pricing depends on road length, existing condition, slope and drainage issues, required aggregate, and travel time. Once we review your map location and photos, we provide a clear, no-obligation estimate and scope of work. </p>
    <p> Still unsure if your road is a fit? Send us the location and we’ll let you know. </p>
  </main>
  <comments/>
</doc>
"#
    
  }
}

test BuildLandingPageXMLSpec3{
  functions [UserResponseOrCoder2]
  args {
    messages [
      {
        role "user"
        content #"Change color of the headline to green.
        "#
      },
      {
        role "assistant"
        content #"Which headline do you want to change to green: the main headline at the top of the page, or the section headline that says “Protect Vehicles and Guests”?"#
      },
      {
        role "user"
        content #"Yes, that one."#
      },
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml", "SPEC.md"]
    spec #"
      GravelGuard — Executive Summary
Status: Demo/concept only. Not trading, no real customers.
Purpose: Validates market positioning and service framing for a mobile gravel road repair business before a full build-out. The primary conversion signal is inbound assessment requests.
Target audience: A mix of institutional buyers (forest agencies, BLM/DNR, counties) and individual/small-org buyers (rural property owners, Airbnb hosts, HOAs, outdoor brand sponsors). Pricing and messaging serve both without a separate funnel for each.
Geography: Pacific Northwest only. Service area not yet formally defined.
Theme: Dark. No inline styles — all styling via Bootstrap utility classes and custom named classes.
CTAs: Primary — "Request a Road Assessment" (modal contact form). Secondary — "View Pricing" (anchor scroll).
Tech stack: Static HTML/CSS/JS. Bootstrap 5.3.8 from jsDelivr CDN. Google Material Icons from Google Fonts CDN. System font stack — no external font files. Mobile-first responsive layout.
SEO: Fully configured — index, follow, Open Graph, Twitter Card, and LocalBusiness JSON-LD schema.
Analytics: Google Analytics 4, property G-YDY6J4DY62. Actively monitored by the owner.
Integrations: Form submissions route to the owner's email inbox via staticforms.xyz. No CRM in the loop — lead follow-up is manual.
Testimonials: Placeholder. Not from real customers.
Ownership: All accounts (hosting, analytics, form backend, email) held directly by the business owner.
Compliance: No cookie consent banner before GA4 fires. No privacy policy exists. The site is not currently receiving real traffic.
Deployment: Managed via the Breba platform on a breba.site subdomain. No custom domain configured.

  <doc sitename="gravel.breba.site" title="GravelGuard | Fast Gravel Road Repair for Trailheads and Rural Access" url="https://gravel.breba.site" hostname="breba.site" description="GravelGuard provides fast gravel road repair for trailheads, campgrounds, rural driveways, and access roads, fixing potholes, washboards, and drainage issues." tags="gravel road repair, trailhead access, rural driveway maintenance, pothole repair, washboard road, recreation access, road grading, GravelGuard" fingerprint="bc9f4c760db66305">
  <main>
    <head rend="h3">Protect Vehicles and Guests</head>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile Gravel Road Repair</p>
    <p>GravelGuard sends mobile crews to repair potholes, washboards, and drainage failures on remote gravel roads so drivers, hikers, and guests can get through safely.</p>
    <list rend="ul">
      <item>Trailheads, campgrounds, rural driveways, and recreation roads</item>
      <item>Fast-response crews with compact graders and professional equipment</item>
      <item>Flexible options for agencies, landowners, and outdoor sponsors</item>
    </list>
    <p>We focus on the rough, forgotten gravel roads that matter most for trail access, rural living, and outdoor tourism—and we keep them passable without big-contractor complexity.</p>
    <p>Reduce tire blowouts, suspension damage, and scary access stories with properly graded, compacted gravel roads.</p>
    <p>Mobile crews restore short road segments in 24–72 hours, ideal for trailheads, cabins, Airbnbs, and seasonal spikes.</p>
    <p>Clear scopes, simple pricing, and sponsor options help agencies, clubs, and brands keep key recreation roads open.</p>
    <p>From a rough GPS pin to a smooth, drivable road in a few simple steps.</p>
    <p> 1 Share the Problem </p>
    <p>Send us a map link or GPS pin for the bad road segment, plus a few photos or a brief description.</p>
    <p> 2 Get a Fast Assessment </p>
    <p>We review satellite imagery and your photos, then send a clear scope, estimated timeline, and pricing options.</p>
    <p> 3 Crew Deploys and Repairs </p>
    <p>Our mobile crew arrives with compact graders, water, and aggregate to fix potholes, break washboards, and restore drainage—often in a single day.</p>
    <p> Want ongoing gravel road maintenance instead of one-off fixes? Ask about our seasonal subscriptions for rural driveway maintenance and recreation access roads. </p>
    <p>From rural driveways to busy trailheads, GravelGuard helps keep access open.</p>
    <p>“We had a trailhead road that everyone complained about for years. GravelGuard had it graded, compacted, and draining properly in a day, and the calls stopped.”</p>
    <p>“Our Airbnb guests used to message us about the washboarded driveway. After GravelGuard’s subscription service, reviews mention the ‘easy access’ instead.”</p>
    <p>“Sponsoring a popular trail access road with GravelGuard gave us real impact and great content. We can literally show customers the road we keep open.”</p>
    <p>Every road is different. These example packages help you understand where most projects land. Exact pricing depends on length, condition, and material needs.</p>
    <p>Most Popular</p>
    <p>Starting from $3,000</p>
    <p>For 0.5–3 miles of rough gravel road leading to trailheads, campgrounds, and recreation areas.</p>
    <list rend="ul">
      <item>Pothole filling and washboard removal</item>
      <item>Basic re-crowning and drainage touch-ups</item>
      <item>Before/after documentation for stakeholders</item>
    </list>
    <p>Starting from $2,000 / visit</p>
    <p>Seasonal maintenance for rural driveways, cabins, Airbnbs, small HOAs, and private roads.</p>
    <list rend="ul">
      <item>Scheduled grading every 3–6 months</item>
      <item>Priority response after storms or freeze–thaw damage</item>
      <item>Predictable access for guests and deliveries</item>
    </list>
    <p>Custom contracts</p>
    <p>For land agencies, counties, timber companies, and outdoor brands sponsoring recreation access.</p>
    <list rend="ul">
      <item>Micro-contracts for short segments</item>
      <item>Sponsor-a-Road and co-branded signage</item>
      <item>Emergency response after major events</item>
    </list>
    <p>Need help estimating your road length or condition? We can walk through it over a quick call.</p>
    <p>If you don’t see your question here, include it in your message and we’ll respond directly.</p>
    <p> We focus on gravel and unpaved access roads that serve trailheads, campgrounds, rural homes, cabins, small HOAs, and recreation areas. We’re best suited for short segments that are too small or low-priority for large contractors. </p>
    <p> Most jobs are assessed within 24 hours on business days, and field work is typically scheduled within 24–72 hours after approval, depending on weather, crew availability, and material needs. </p>
    <p> Yes. We regularly partner with forest agencies, BLM and DNR districts, counties, and timber companies to handle small segments, emergency washouts, and recreation-focused roads that don’t fit traditional contracts. </p>
    <p> Absolutely. Our Sponsor-a-Road model lets outdoor brands, breweries, clubs, and donors fund improvements on specific access roads with clear recognition and impact reporting. </p>
    <p> Pricing depends on road length, existing condition, slope and drainage issues, required aggregate, and travel time. Once we review your map location and photos, we provide a clear, no-obligation estimate and scope of work. </p>
    <p> Still unsure if your road is a fit? Send us the location and we’ll let you know. </p>
  </main>
  <comments/>
</doc>
"#
    
  }
}