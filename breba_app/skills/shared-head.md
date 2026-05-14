Use this when needing to extract shared head component to be shared with other pages
<shared-head>
Extract shared head like core styles (e.g. bootstrap, and styles.css) the fonts, favicon, and analytics.
Make sure that you only put content into shared components if it is logically or functionally shared.
For example, SEO tags are per page and should never be shared. Things that are conincidentally the same, but logically or functinoally do not belong together should not be in a shared component


Each component needs to have a comment at the top and at the bottom. This helps with code organization and readability.

</shared-head>
