This will be static pages using HTML JS and CSS. The form will be handled by staticforms.xyz

When you need a mobile sandwich menu:

Use Bootstrap 5.3.8 via CDN for core styling (without integrity check):
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">                                                                                                                                            
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>                                                                                                                                              

To make sure the collapse menu animation works smoothly, need to make sure there is no vertical resizing of the menu
when the items are opened or
closed.                                                                                         
For the collapse items make sure there is no additional padding or margin or gap. Extra space on the top of the collapse
items causees jerky resizing when the collapse menu disappears. Bootstrap animates the collapse menu disappearing,
but   
the resizing is sudden and that is why we need avoid it.

You can use placeholders for image or use public images for now. I will upload image later

## Design System

- You will come up with a color palette, typography, spacing, and other design elements

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

We are producing a production ready website that geared towards search engine discoverabilty and core web vitals.

Keep in mind, this project is a website that follows best practices.

1. Use semantic HTML tags
2. IMPORTANT: You must avoid using inline style attribute. Always try to use CSS classes.
3. Never generate inline SVG. Instead use google icons or other publicly available icons.
4. Use utility classes for layout and spacing, and component classes for reusable UI elements.
5. Try to keep the code clean, dry, and concise
6. Make sure your changes are taking into account existing code and make good holistic changes.
7. When using styles, prefer "rem" units. Avoid "em" units, if possible.
8. Use the html lang attribute. Default to english.
9. Keep styles clean. Make sure we don't have style bloat and unnecessary duplication of properties.
10. Make sure images and fonts are loaded in a way that is optimal for performance.
11. Avoid styles that could cause horizontal scrolling.
12. Make sure to optimize for SEO and core web vitals.
13. Make sure to update sitemap.xml for any visible content changes.
14. A production ready website must have robots.txt file.
15. Must be responsive (use clamps for font sizes, gaps, padding, etc.)
16. Always consider font color and background contrast for readability. 