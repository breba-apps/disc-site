landing_page_instructions = f"""
# Instructions for building a Services Landing Page

## Questions to ask
- **You will only ask these exact questions, and no other questions**
1. Ask to provide a business description and services provided.
2. Ask about Design system in non-technical terms and may not be familiar website design (ask a couple questions and then come up with the design system)
3. Upload hero image -- the big, eye-catching visual at the very top of a webpage. When uploading please specify if the colors in the image are dark, light, or bright.
4. Upload logo (if no logo, make a pretty text logo using one or two design system colors).

Notes to developer: 
1) if no logo, make a pretty text logo using one or two design system colors.
2) If no hero image is provided, use CSS to create a hero background. Background could have geometrical shapes, a patterns, and minor animation. IMPORTANT: animation should be subtle, short and not distracting (no continuous animation loops).
 
## Design System
- You will come up with a color palette, typography, spacing, and other design elements.(Do not ask direct questions about this, just make up whatever you think makes sense given answers to your questions)

## Layout
- You will have a sticky navbar that stays on top as you scroll.
  - The navbar will have a logo and a call to action button
  - Social media buttons all the way in the right corner 
- Full page hero section with a call to action button and a catchy slogan.
  - The main heading and the subtext should centered in the hero section
  - CTA buttons below the subtext
  - Navbar is liquid glass
  - For mobile, make sure that when the sandwich button is clicked, the rolled out items have a contrasting background color
  - For mobile, make sure that the sandwich button color contrasts the background (whatever it is)
- Testimonials section with 6 testimonials
- FAQs section with 5 questions based on the business plan
- Footer with social media icons
- Contact form to be show up in a modal with the following fields: Name, Email, Message
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
- Do not use inline styles.

## Defaults (Use this unless user specifies other preferences)
- Use Google icons or other publicly available images when appropriate
- Use Bootstrap 5.3.8 via CDN for core styling (without integrity check):
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>
  """

