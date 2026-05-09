class Question {
  question string @description("Question that requires the user to answer")
}

class WebsiteSpecification {
  spec string @description("Full website specification")
}

class LLMMessage {
  role "user" | "assistant"
  content string
  images image[]?
}

template_string  SystemInfo() #"
    <system_info>
    You are working within Breba website builder application.
    The website may be a single-page site (index.html) or a multi-page site with shared components reused across pages.
    </system_info>

    <limitation>
    When user asks you to do something that you cannot do, tell them.
    1) You cannot view or analyze website urls or any content behind them.
    2) You cannot analyze video or audio.
    3) You cannot analyze PDF files
    </limitation>
"#

template_string TemplatingInstructions() #"
**You will ask questions** (unless the user indicates they don't want questions)
Ask ONE question at a time and wait for the answer before asking the next question.
Questions must be simple and easy to answer with one word or a short phrase.
"#

template_string GoodWebsiteSpecification() #"
**Generating good website specifications**
The website specification must be self-contained and NOT reference any parts of the conversation with the user. Do not introduce extra or one-off instructions in the specification.

You are not providing the user an answer, instead you are producing a complete and concise website specification for the development team.
The HTML generator will use only the final website specification to build the website, so make sure the specification is concise, complete, and includes all required sections, elements, and text—nothing more.
After all user questions are answered, respond ONLY with the finalized website specification. Do NOT include extra explanations or additional narrative.

Produce a high quality PRD that is clear and concise. Avoid repeating instructions and unnecessary sections.

Here is an example of a website specification:

# 🎂 Birthday Website Specification

## 1. Overview

This is a static HTML website for a personal birthday celebration. It will be shared with friends and presents all key event information clearly, with an embedded Google Form for RSVP.

The site must be:
- Elegant and modern-minimal in style
- Mobile-friendly and easy to navigate

---

## 2. Design System
- **Overview**: Clean, classy, modern-minimal. No visual clutter or unnecessary animations.
- **Typography**: Clean sans-serif for body text; elegant serif for headings
- **Colors**:
  - Background: #FFFFFF
  - Text: #000000
  - Accent Gold: #C8A95A
  - Divider Gray: #E5E5E5
- **Layout**:
  - Max content width: ~900px
  - Centered column layout
  - Mobile padding: 20–24px
- **Theme**:
  - Light theme
- **Shared Components**: Navbar and footer are reused across all pages

---

## 3. Content to Include

### Hero Section

- **Title**: _"You're invited to Yason’s birthday!"_
- **Photo**: Image from `https://cdn.breba.app/abc/123/my_photo.png`

---

### Event Details

- **Date**: July 7, 2025
- **Time**: 7:00 PM
- **Location**: 123 ABC St, Seattle, WA
- **Dress Code**: Black and White

---

### RSVP Section

- Embed Google Form: `https://forms.gle/gtPhM82xcEXF9YaKA`
- Responsive iframe
- Heading: _"Let me know if you’re coming!"_
- Match form styling to site if possible

---

### Available assets
https://cdn.breba.app/images/logo_light.png - Use this for logo image for the light theme
https://cdn.breba.app/images/avatar.png - Use this for my avatar
"#


function GenerateSpecificationFromTemplate(messages: LLMMessage[]) -> Question | WebsiteSpecification {
  client Gpt5Low
  prompt #"
    You are a product manager crafting a website specification (PRD). 
    You are non-technical and will produce a specification that can be read by someone without understanding of HTML.
    Use non-technical terms to describe the website. 
    Do not make up technical limitations or constraints.

    {{ SystemInfo() }}

    {{ TemplatingInstructions() }}

    {{ GoodWebsiteSpecification() }}    

    {% for message in messages %}
      {{ _.role(message.role) }}
      {{ message.content }}
      {% if message.images %}
        {% for image in message.images %}
          {{ image }}
        {% endfor %}
      {% endif %}
    {% endfor %}

    {{ _.role("system") }}
    {{ ctx.output_format }}

  "#
}

test BuildTheActualSpec {
  functions [GenerateSpecificationFromTemplate]
  args {
    messages [
      {
        role "user"
        content #"
# Instructions for building a Landing Page

## Questions to ask
- **You will only ask these exact questions, and no other questions**
1. Ask to provide a business plan or a detailed description of business idea.
2. Ask about Design system in non-technical terms and may not be familiar website design (ask a couple questions and then come up with the design system)

## Design System
- You will come up with a color palette, typography, spacing, components, and other design elements.(Do not ask direct questions about this, just make up whatever you think makes sense given answers to your questions)

## Layout
- You will have a navbar that scrolls to different section of the page.
  - The navbar will have a logo and a call to action button
- At the top the hero section with a call to action button and a catchy slogan.
- Then Benefits section with 3 benefits
- Then How It Works section with 3 steps
- Then Testimonials section with 3 testimonials
- Then Pricing section with 3 pricing plans
- FAQs section with 5 questions based on the business plan
- Footer with social media icons
- Modal form with fields: Name, Email, Company, Message
  - the form will use staticforms.xyz with ajax for submission.
  - The form will have hidden fields for: subject, replyTo, apiKey.

## SEO
- You must fill out all SEO tags.

## Technical requirements
- The page should be responsive (use clamps for font sizes, gaps, padding, etc.)
- The page should be mobile-first.
- The page should be accessible.
- The page should be optimized for speed.
- The page should be optimized for security.
- The page should be optimized for SEO.
- The page should support Google Analytics.
- Do not use inline styles.

## Defaults (Use this unless user specifies other preferences)
- Use Google icons or other publicly available images when appropriate
- Use https://cdn.breba.app/templates/images/logo.png as the logo in the navbar and anywhere else a logo appears.
- Use https://cdn.breba.app/templates/images/hero.jpg as the hero image in the Hero section.
- Use Bootstrap 5.3.8 via CDN for core styling (without integrity check):
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script># Landing Page Template
  IMPORTANT: do not use integrity check

"#
      }
      {
        role "assistant"
        content "Please provide a brief business plan or a detailed description of your business idea."
      }
      {
        role "user"
        content "We are changing the way people treat documents. We are proposing that everything is a document or deserves a document. You morning routine is a document, your vacation plan is a document. And we will have AI agents who help you organize documents and present you the relevant info and documents when you need it."
      }
      {
        role "assistant"
        content "What overall vibe should the site convey (e.g., futuristic, friendly, professional, playful) and do you prefer light or dark theme?"
      }
      {
        role "user"
        content "Brutalist."
      }
    ]
  }
}

test AskingSecondQuestion {
  functions [GenerateSpecificationFromTemplate]
  args {
    messages [
      {
        role "user"
        content #"
# Instructions for building a Landing Page

## Questions to ask
- **You will only ask these exact questions, and no other questions**
1. Ask to provide a business plan or a detailed description of business idea.
2. Ask about Design system in non-technical terms and may not be familiar website design (ask a couple questions and then come up with the design system)

## Design System
- You will come up with a color palette, typography, spacing, and other design elements.(Do not ask direct questions about this, just make up whatever you think makes sense given answers to your questions)

## Layout
- You will have a navbar that scrolls to different section of the page.
  - The navbar will have a logo and a call to action button
- At the top the hero section with a call to action button and a catchy slogan.
- Then Benefits section with 3 benefits
- Then How It Works section with 3 steps
- Then Testimonials section with 3 testimonials
- Then Pricing section with 3 pricing plans
- FAQs section with 5 questions based on the business plan
- Footer with social media icons
- Modal form with fields: Name, Email, Company, Message
  - the form will use staticforms.xyz with ajax for submission.
  - The form will have hidden fields for: subject, replyTo, apiKey.

## SEO
- You must fill out all SEO tags.

## Technical requirements
- The page should be responsive.
- The page should be mobile-first.
- The page should be accessible.
- The page should be optimized for speed.
- The page should be optimized for security.
- The page should be optimized for SEO.
- The page should support Google Analytics.
- Do not use inline styles.

## Defaults (Use this unless user specifies other preferences)
- Use Google icons or other publicly available images when appropriate
- Use https://cdn.breba.app/templates/images/logo.png as the logo in the navbar and anywhere else a logo appears.
- Use https://cdn.breba.app/templates/images/hero.jpg as the hero image in the Hero section.
- Use Bootstrap 5.3.8 via CDN for core styling (without integrity check):
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script># Landing Page Template

"#
      }
      {
        role "assistant"
        content "Please provide a brief business plan or a detailed description of your business idea."
      }
      {
        role "user"
        content "We are changing the way people treat documents. We are proposing that everything is a document or deserves a document. You morning routine is a document, your vacation plan is a document. And we will have AI agents who help you organize documents and present you the relevant info and documents when you need it."
      }
    ]
  }
}