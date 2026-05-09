<material_icons_font>
Use these instructions if you need to use material icons font.

Only load material icons that are actually used on the website. 
Example:
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,500,0,0&icon_names=check_circle,expand_more,hub,key,star,target" rel="stylesheet">
IMPORTANT: Remember the icon_names must be in alphabetical order, otherwise the font will not work.
</material_icons_font>
<font_selection>
Use these instructions if you need to use font selection.
Do not load more than 4 custom fonts. Use system fonts if needed.
</font_selection>
<font_performannce>
Fonts should be loaded after css especially bootstrap. Loading CSS first prevents layout shifts.
</font_performannce>

## Custom Fonts layout shift prevention
<custom_fonts>
Use minimal custom fonts above the fold.
To make sure animations and other layout shifts are not visible, you can use javascript to run animations after font is loaded.
document.fonts.load('600 1em Poppins').then(() => {
  document.documentElement.classList.add('fonts-ready');
});
</custom_fonts>

<render_blocking_requests>
Make sure to use preconnect and preload where appropriate (too many is not helpful).
Only the main css file like bootstrap.css or styles.css(names could vary) must load while blocking rendering.
All fonts must be loaded in a non-blocking fashion.
Preconnects should appear before downloading the render block css for the page.
</render_blocking_requests>

<navbar_sizing_consistency>
Navbar needs to be sized without any jerky movements. For example, on mobile, when navbar collapses. 
The collapsing effect itself is an animation. If the collapse element has padding or anything that effects the navbar height, 
It will disappear after the smooth animation hiding nav links. This results in a non-smooth resize of the navbar.
You must avoid this behavior.
You must avoid having JavaScript that resizes navbar.
