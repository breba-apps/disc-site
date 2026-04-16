landing_page_instructions = f"""
# Instructions for building a Landing Page

## Questions to ask
- **You will only ask these exact questions, and no other questions**
1. Ask to provide a business description and services provided.
2. Ask about Design system in non-technical terms and may not be familiar website design (ask a couple questions and then come up with the design system)
3. Upload hero image -- the big, eye-catching visual at the very top of a webpage. When uploading please specify if the colors in the image are dark, light, or bright.
4. Upload logo (if no logo, make a pretty text logo using one or two design system colors).

Notes to developer: 
1) If no logo, make a pretty text logo using one or two design system colors.
2) If no hero image is provided, use CSS to create a hero background. Background could have geometrical shapes, a patterns, and minor animation. IMPORTANT: animation should be subtle, short and not distracting (no continuous animation loops).

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
- Use Bootstrap 5.3.8 via CDN for core styling (without integrity check):
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
"""

landing_page_follow_up_questions = [
    {
        "title": "SEO",
        "question": """I want to finalize SEO. Let's work on SEO. I'm not a developer and don't know anything about html tags.
Ask me questions to make sure SEO is correct. 
Do not make assumptions and do not make anything up. Ask as many questions as necessary.
Ask one question at a time and wait for response before asking the next question. When asking questions about text, such as title and description, make a suggestion.
End result must have production ready SEO tags including, but not limited to:
title, description, canonical url, viewport for mobile-first indexing, og graph, twitter card, schema.org structured data, robots index and follow.
"""
    },
    {
        "title": "Social Media",
        "question": """I want to finalize social media icons in the footer. 
Ask me questions to make sure social media in the footer are correct. 
Do not make assumptions and do not make anything up. Ask as many questions as necessary.
End result must have the correct social media icons in the footer. 
Ask one question at a time and wait for response before asking the next question."""
    },
    {
        "title": "Call to action",
        "question": """I want to finalize the call to action form. 
        Ask me questions to make sure form apiKey and subject fields are correct.
Ask one question at a time and wait for response before asking the next question.
End result must have a fully functional form that works with the outside provider and no remaining questions to ask. 
If I cannot answer your questions for some reason, just use default values. I'm not a developer.


Don't ask questions about:
1) Email recipient because this is setup on the backend.
2) replyTo field should be set to "@" which means the email field from the form will be used.
3) Endpoint URL is always https://api.staticforms.xyz/submit
4) Always use honeypot field for security

Always ask questions about apiKey and subject, then you will update the specification.

**Notice that apiKey is the name of the field for staticforms.xyz.**"""
    },
    {
        "title": "Analytics",
        "question": """I want to hook up Google Analytics. Ask questions to setup Google Analytics. 
We will use the instructions for "Add the Google tag directly to your web pages". 
This means asking the user for the script from Google Analytics and then make sure the script goes into the head element. 
End result must have Google Analytics properly setup. 
Ask one question at a time and wait for response before asking the next question.
Remember I'm not a developer. In can follow instructions and copy and paste code from google analytics, but I don't know anything about HTML"""
    },
    {
        "title": "Favicon",
        "question": "I want to upload a favicon are you ready?"
    },
]
