class ImageClassification{
  intent string @description(#"
    User intent for the upload
  "#)
  reason string @description(#"
    Reason why you chose this intent
  "#)
}

class QuestionToUser{
  response_to_user string @description("Clarification of the issue with the request")
}


class UplaodAsset{
  upload_asset bool @description(#"
    User needs to upload assest to be used as part of website contents.
  "#)
  inference bool @description(#"
    Always true
  "#)
  reason string @description(#"
    Reason why you chose to upload the assets
  "#)
}

class Inference{
  inference_only bool @description("Always true")
}

function DescribeMedia(messages: LLMMessage[]) -> ImageClassification | QuestionToUser{
  client "CustomGPT5Mini"  // GPT-5 has excellent multimodal support
  // Most LLM providers require images or audio to be sent as "user" messages.
  prompt #"You are an AI agent working the with user and other agents to build a website. 
  The website is a fully functonal production website. `assets` folder is used for images and files that will be rendered by the browser.
  Your job is to determine if user provided assets need to uploaded to the `assets` folder of the website. 
  After you determine the intent, other software will further analyze the context of the conversation and take actions.
  Files don't need to be uploaded to the `assets` folder for inferencing.
  Intent can be `asset`, `inference`. Intent can be only a single word.
  IMPORTANT: Confront user if something doesn't make sense. Tell them what doesn't make sense.

    When images uploaded don't make sense given the context, you will respond to user by explaining the semantic issue with the request (the user needs to understand why their request doesn't make sense).
    Remind the user to upload correct files. Only the images in the last user request will be processed.
    <reasons_for_response_to_user>
    1. If things don't make sense as far as semantics of website building goes.
    2. The expected number of files being uploaded is not matching the semantic context.(too many or too few images)
    2.1. Too many files were uploaded for a given request.
    2.2. Not enough files were uploaded for a given request.
    3. Image content or size does not seem appropriate for the request.
    4. Anything doesn't make sense given the context, you will respond to the user instead of picking an intent.
    </reasons_for_response_to_user>
    <reasons_for_asset>
    IMPORTANT: Assets in the assets folder are used in the HTML and will interpreted or rendered by the browser.
    IMPORTANT: Inferencing and sampling and extracting is always performed on all files. Files do not need to be added to the assets folder to extract information from them.
    1. User wants the exact images to show up on the website.
    2. User wants the exact images as part of HTML of the website.
    3. User wants the exact uploaded files to be part of the website.
    </reasons_for_asset>
    <reasons_for_inference_intent>
    1. Use `inference` intent if the user provided files simply need to be interpreted and not be part of the HTML.
    2. Images that are provided for reference or sampling only.
    3. User is providing screenshots
    4. User is providing samples
    </reasons_for_inference_intent>


    {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.images }}
      {{ message.content }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}

function PickActionForUpload(messages: LLMMessage[]) -> UplaodAsset | Inference | QuestionToUser{
  client "CustomGPT5Mini"  // GPT-5 has excellent multimodal support
  // Most LLM providers require images or audio to be sent as "user" messages.
  prompt #"You are an AI agent working the with user and other agents to build a website. 
  The website is a fully functonal production website. `assets` folder is used for images and files that will be rendered by the browser.
  Your job is to determine if user provided assets need to uploaded to the `assets` folder of the website. 
  After you determine the intent, other software will further analyze the context of the conversation and take actions.
  Files don't need to be uploaded to the `assets` folder for inferencing.
  Intent can be `asset`, `inference`. Intent can be only a single word.
  IMPORTANT: Confront user if something doesn't make sense. Tell them what doesn't make sense.

    When images uploaded don't make sense given the context, you will respond to user by explaining the semantic issue with the request (the user needs to understand why their request doesn't make sense).
    Remind the user to upload correct files. Only the images in the last user request will be processed.
    <reasons_for_response_to_user>
    1. If things don't make sense as far as semantics of website building goes.
    2. The expected number of files being uploaded is not matching the semantic context.(too many or too few images)
    2.1. Too many files were uploaded for a given request.
    2.2. Not enough files were uploaded for a given request.
    3. Image content or size does not seem appropriate for the request.
    4. Anything doesn't make sense given the context, you will respond to the user instead of picking an intent.
    </reasons_for_response_to_user>
    <reasons_for_uploading_asset>
    IMPORTANT: Upload assets when they need to be part of website structure or metadata.
    IMPORTANT: Inferencing and sampling and extracting is always performed on all files. Files do not need to be added to the assets folder to extract information from them.
    1. User wants the exact images to show up on the website.
    2. User wants the exact images as part of HTML of the website.
    3. User wants the exact uploaded files to be part of the website.
    </reasons_for_uploading_asset>
    <reasons_for_inference_intent>
    1. Use `inference` intent if the user provided files simply need to be interpreted and not be part of the HTML.
    2. Images that are provided for reference or sampling only.
    3. User is providing screenshots
    4. User is providing samples
    </reasons_for_inference_intent>


    {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.images }}
      {{ message.content }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}

// See the "testing functions" Guide for more on testing Multimodal functions
test TestAddImages {
  functions [DescribeMedia]
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


test DebuggingWebsite {
  functions [DescribeMedia]
  args {
    messages [
      {
        role "user"
        content #"The navbar looks completely wrong"#
        images [
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
          {url "https://cdn.breba.app/templates/images/image_2.jpg"}
        ]
      }
    ]
  }
}


test MultiturnUpload {
  functions [DescribeMedia]
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

test MultiturnDebug {
  functions [DescribeMedia]
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
          {url "https://cdn.breba.app/templates/images/image_123.jpg"}
          {url "https://cdn.breba.app/templates/images/image_2.jpg"}
        ]
      }
      
    ]
  }
}


test QuestionAboutLogos {
  functions [PickActionForUpload]
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

test QuestionAboutLogosFollowUp {
  functions [DescribeMedia]
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
      },
      {
        role "assistant"
        content "You uploaded two images but asked to use a logo. These images look like artwork/photographs, not a single logo file. Please upload the correct logo file (preferably a single image in PNG, SVG, or high-resolution transparent background) so I can add it to your website."
      }
      {
        role "user"
        content #"I want to use my logo"#
        images [{url "https://cdn.breba.app/templates/images/logo.png"}]        
      },
    ]
  }
}


test CreateWebsite {
  functions [DescribeMedia]
  args {
    messages [
      {
        role "user"
        content #"I want my website to have colors like these."#
        images [
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/dinasaur-bird.jpeg"},
          {url "https://cdn.breba.app/yason/6ad11b75bf554afc9517882ddd1bfced/assets/Goals.jpeg"}
        ]
      },
    ]
  }
}