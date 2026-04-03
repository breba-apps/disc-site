// upload_intent.baml
//
// All uploaded images are ALWAYS passed to the AI for inference.
// The only question is: should we ALSO copy them to the assets folder?
//
// Design: default is NO (don't upload to assets). Only upload when
// the user clearly wants the exact file served as part of the website.
// When in doubt, ask.

class UploadToAssets {
  image_description string @description("One sentence description of the image(s) that were uploaded, in context of the conversation.")
  reason string @description("One sentence explaining why upload is true or false.")
  upload bool @description("True only if the user explicitly wants this file displayed on their website.")
  problem string @description("One sentence explaining why the images provided are not suitable for uploading to assets. Empty string when upload is false.")
}

function ShouldUploadToAssets(messages: LLMMessage[]) -> UploadToAssets {
  client "CustomGPT5Mini"
  prompt #"You decide whether uploaded images should be copied into a website's assets folder.

IMPORTANT: Every uploaded image is ALREADY analyzed by AI agents automatically.
The ONLY reason to upload to assets is if the file must be served as part of the website HTML (e.g. displayed in an <img> tag, used as a background, favicon, etc.).

YOUR DEFAULT: Do NOT upload to assets (upload: false).
If you are unsure, set upload to false and provide a reason explaining why you are not sure.

Your logic is as follows:
1. Determine user intent (upload or not).
2. If upload, check that payload is appropriate for the request. Payload is number/types of images and images contents.
3. Report problem if payload is not appropriate for the request.

<when_to_upload_true>
Set upload to true when the user clearly wants the exact image served on their website:
- User explicitly names where it goes: "add this to my header", "use this as my hero background"
- User says the images are for a specific section of their site: "here are images for my X"
- User confirms after being asked (e.g. "yes, add them")
</when_to_upload_true>

<when_to_upload_false>
Set upload to false when:
- User provides screenshots to report a problem or give feedback (e.g. "this looks wrong", "the X is broken")
- User says "like this", "similar to", "inspired by", "based on" (reference only)
- User wants colors extracted, styles copied, or layouts mimicked
- User provides mockups, wireframes, or design samples
- The assistant asked for a screenshot and the user provided one
- User is asking for analysis or description of the image
</when_to_upload_false>

<reason_style>
The `reason` field must always be non-empty. Very short single sentence.
</reason_style>

<problem_guidance>
IMPORTANT: problem only reports an issue if upload is true. If upload is false, problem should be empty.
IMPORTANT: If the number of images doesn't match what the user described (e.g. "my logo" + 3 images), report a problem.
- Mismatch: explain BOTH what you see AND why it doesn't fit the request. The user may not realize they attached the wrong files.
  - Good: "I see a bird photo and what looks like a goals checklist — neither looks like a logo, so I'm not sure these are the right files."
  - Good: "I see 3 very different images, but you mentioned a single logo — it's unclear which one (if any) is your logo."
- Ambiguity: explain what's unclear about intent.
  - Good: "No message was provided, so it's unclear whether these should go on the website or are just for reference."
- Bad: "I see two illustrated animal images." (describes content but doesn't say what the problem is)

</problem_guidance>

{% for message in messages %}
  {{ _.role(message.role) }}
  {{ message.images }}
  {{ message.content }}
{% endfor %}

{{ ctx.output_format }}
"#
}

// --- Tests ---

// upload=true, problem="" — user names a website section, which is explicit intent to publish.
test VagueGalleryUpload {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Here are some pictures for my gallery"#
        images [
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/dinasaur-bird.jpeg"},
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/Goals.jpeg"}
        ]
      }
    ]
  }
}

// upload=false, problem="" — user is reporting a bug, not adding images to the site.
test ScreenshotDebug {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"The navbar looks completely wrong"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"},
          {url "https://cdn.breba.app/templates/images/image_2.jpg"}
        ]
      }
    ]
  }
}

// upload=true, problem="" — user expressed intent to use their logo; single image uploaded matches.
test LogoUploadAmbiguous {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"I want to use my logo"#
      },
      {
        role "assistant"
        content #"I don't have any logos for your website."#
      },
      {
        role "user"
        content #""#
        images [
          {url "https://cdn.breba.app/templates/images/logo.png"}
        ]
      }
    ]
  }
}

// upload=true, problem=non-empty — intent is to use logo, but uploaded images don't look like a logo.
test LogoMismatch {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"I want to use my logo"#
      },
      {
        role "assistant"
        content #"I don't have any logos for your website."#
      },
      {
        role "user"
        content #""#
        images [
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/dinasaur-bird.jpeg"},
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/Goals.jpeg"}
        ]
      }
    ]
  }
}

// upload=false, problem="" — assistant asked for a screenshot; user provided one for debugging.
test AssistantAskedForScreenshot {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Something is wrong with the site"#
      },
      {
        role "assistant"
        content #"Can you upload a screenshot?"#
      },
      {
        role "user"
        content #""#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"},
          {url "https://cdn.breba.app/templates/images/image_2.jpg"}
        ]
      }
    ]
  }
}

// upload=false, problem="" — "colors like these" is reference/inspiration, not a file to serve.
test ColorInspiration {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"I want my website to have colors like these."#
        images [
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/dinasaur-bird.jpeg"},
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/Goals.jpeg"}
        ]
      }
    ]
  }
}

// upload=false, problem="" — no message context; intent cannot be determined, default to false.
test BareUploadNoContext {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #""#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
        ]
      }
    ]
  }
}

// upload=true, problem="" — explicit placement instruction with matching single image.
test ExplicitAddToHero {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Put this image as the hero background"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
        ]
      }
    ]
  }
}

// upload=false, problem="" — "look like this" is a design reference, not a file to serve.
test LikeThisDesign {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"I want my site to look like this"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
        ]
      }
    ]
  }
}

// upload=true, problem=non-empty — intent is to use logo, but 2 images uploaded when 1 was implied.
test MismatchedCountAndRequest {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Here's my company logo"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"},
          {url "https://cdn.breba.app/templates/images/image_2.jpg"},
        ]
      }
    ]
  }
}

// upload=true, problem="" — user explicitly confirms they want the images added.
test ConfirmedAfterQuestion {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Here are some pictures for my gallery"#
        images [
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/dinasaur-bird.jpeg"},
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/Goals.jpeg"}
        ]
      },
      {
        role "assistant"
        content "Should I add these images to your website's gallery, or are they examples of the style you want?"
      },
      {
        role "user"
        content "Yes, add them to my gallery"
      }
    ]
  }
}

// upload=false, problem="" — "similar to this" is a reference, not a file to serve.
test MakeSomethingSimilar {
  functions [ShouldUploadToAssets]
  args {
    messages [
      {
        role "user"
        content #"Can you make a banner similar to this?"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
        ]
      }
    ]
  }
}
