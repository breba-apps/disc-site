When you need a mobile sandwich menu:

Use Bootstrap 5.3.8 via CDN for core styling (without integrity check): 
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>

To make sure the collapse menu animation works smoothly, need to make sure there is no vertical resizing of the menu when the items are opened or closed.
For the collapse items make sure there is no additional padding or margin or gap. Extra space on the top of the collapse items causees jerky resizing when the collapse menu disappears. Bootstrap animates the collapse menu disappearing, but the resizing is sudden and that is why we need avoid it.