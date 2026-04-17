template_string RulesForExecutiveSummary() #"
Rules:
1. Be extremely concise.
2. Do not repeat information.
3. Do not include explanations, reasoning, or filler.
4. Prefer concrete facts over narrative wording.
5. Do not invent missing details.
6. Keep the output compact.
7. The information you exttract should be fewer words than the original user input. You are trying to extract meaning.
8. IMPORTANT: DO NOT EXTRACT IMPLEMENTATION DETAILS. THOSE WILL GO INTO HTML. YOUR JOB IS TO EXCTRACT: intents, invariants, decisions, preferences, and constraints. DO NOT EXTRACT IMPLEMENTATION DETAILS. DO NOT EXTRACT THINGS LIKE "Use a dark theme". INSTEAD, EXTRACT THE PREFERENCE "Dark theme" WITHOUT SAYING ANYTHING ABOUT IMPLEMENTATION.
9. DO NOT EXTRACT CONTENT OR STRUCTURE DETAILS.
10. DO NOT EXTRACT USER SENTIMENTS OR EMOTIONS. ONLY EXTRACT FACTS AND PREFERENCES.
11. IMPORTANT: Do not extract content requirements. Those will go into the HTML. You are writing notes to supplement the HTML.
12. Do not use imperative language. The notes capture the final state of the user's preferences, decisions, and requirements. They do not include instructions or suggestions.

"#


template_string NewProjectExecutiveSummary(index_html: string) #"
Your job is to read the user's website request and produce a VERY concise summary.
You will capture information about things the user wants, likes, or prefers facts the user or the website, and any constraints or requirements.

{% if index_html %}
  You can infer some details from the existing index.html file to understand the current implementation and extract any relevant details that should be included in the executive summary.
  {{index_html}}
{% endif %}

{{RulesForExecutiveSummary()}}

  <example_executive_summary>
  Background
  James Callfield started his plubmbing business 20 years ago. The business name is "Callfield Plumbing". The business is based in Austin, Texas. James has 10 employees.

  Website Description
  The website is intended to capture leads for the plumbing business.
  It will have two calls to action: 1) Schedule a service appointment and 2) Learn more about our services.

  Visual Preferences
  Dark theme. Simple and clean design. Blue and Grey colors preferred.

  Technical Requirements
  Single HTML file that contains all styles, scripts and html.
  </example_executive_summary>

    "#

template_string ExistingProjectExecutiveSummary() #"
    Update the existing project summary based on the conversation. If there is nothing to update, just say "noop".
    If there are updates, produce the full updated notes, not just the changes.

    {{RulesForExecutiveSummary()}}

    You must ignore content updates.
    If existing executive summary contains details about content, remove them. This is an executive architecture summary.
    "#


function CoderNotes(messages: LLMMessage[], coder_notes: string, index_html: string) -> string {
  client Gpt5Low
    prompt #"You are an AI agent that helps maintain an executive summary of a user project. Analyze user conversation and extract high level information.
    {% if coder_notes %}
        {{ _.role("system") }}
        {{ ExistingProjectExecutiveSummary() }}
    {% else %}
        {{ _.role("system") }}
        {{ NewProjectExecutiveSummary(index_html) }}
    {% endif %}


    {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.content }}
    {% endfor %}

    {% if coder_notes %}
      {{ _.role("assistant") }}
      To update the existing agent instructions, please provide the current instructions.
      {{ _.role("user") }}
      Here is my current website description and preferences. If necessary, update it based on this conversation:
      {{ coder_notes }}

    {% else %}
      {{ _.role("system") }}
      This is a brand new project, so there are no agent instructions yet. Based on our conversation, create the initial agent instructions for this project.
    {% endif %}

  "#
}

test DemoWebsiteNotes {
  functions [CoderNotes]
  args {
    messages [
      {
        role "user"
        content #"Build a hello world website for me. This is a demo. So make it very simple"#
      },
      {
        role "assistant"
        content #"What color scheme do you prefer?"#
      },
      {
        role "user"
        content #"Let's make dark, but it doesn't really matter."#
      }
    ],
    coder_notes "",
    index_html ""
  }
}

test ConsultingWebsiteNotes {
  functions [CoderNotes]
  args {
    messages [
      {
        role "user"
        content #"I run a business called Breba Consulting and I need a landing page for it.
            Hero section shoule include a headline: Like this? I can make one for you.
            The subheading should be: Creating a landing page for your business should not be a chore. I will create a custom landing page for your business in minutes, not days.
            The primary CTA should be "Boook a free consultation" and the secondary CTA should be "See samples of work".
            We will have a section with portfolio. I will fill that in later, but it should have space for 5 projects.

        "#
      },
      {
        role "assistant"
        content #"What color scheme do you prefer?"#
      },
      {
        role "user"
        content #"Let's make dark."#
      }
    ],
    coder_notes "",
    index_html ""
  }
}


test DemoWebsiteNotesFollowUp {
  functions [CoderNotes]
  args {
    messages [
        {
            role "user"
            content #"Actually, I want the website to have a dark theme."#
        },
        {
            role "assistant"
            content #"Okay, should that button gradients, or leave them as is?"#
        },
        {
            role "user"
            content #"Yes, change button gradients to fight dark theme"#
        }

    ],
    coder_notes #"Background  
- Business name: Breba Consulting  

Website Description  
- Single landing page promoting consulting services  
- Focus on offering custom landing pages for clients  

Primary Goals  
- Capture leads via consultation bookings  
- Showcase work samples/portfolio  

Calls to Action  
- Primary CTA: "Boook a free consultation"
- Secondary CTA: "See samples of work"

Content Requirements (High-Level)  
- Hero section with headline and subheading provided by user  
- Portfolio area with capacity for 5 projects (user will add content later)  

Visual Preferences  
- Light theme"#,
    index_html ""
  }
}


test DemoWebsiteNotesFollowUpDuplicateRequest {
  functions [CoderNotes]
  args {
    messages [
        {
            role "user"
            content #"Actually, get rid of secondary CTA."#
        },
        {
            role "assistant"
            content #"Something went wrong?"#
        },
        {
            role "user"
            content #"I said remove secondary CTA button"#
        }

    ],
    coder_notes #"Background  
- Business name: Breba Consulting  

Website Description  
- Single landing page promoting consulting services  
- Focus on offering custom landing pages for clients  

Primary Goals  
- Capture leads via consultation bookings  
- Showcase work samples/portfolio  

Calls to Action  
- Primary CTA: "Boook a free consultation"
- Secondary CTA: "See samples of work"

Content Requirements (High-Level)  
- Hero section with headline and subheading provided by user  
- Portfolio area with capacity for 5 projects (user will add content later)  

Visual Preferences  
- Light theme"#,
    index_html ""
  }
}


test WebsiteNotesFollowUpNoop {
  functions [CoderNotes]
  args {
    messages [
        {
            role "user"
            content #"Change \"You like this landing page?\" to \"Landinge Pages for Everyone\""#
        }
    ],
    coder_notes #"Background  
- Business name: Breba Consulting  

Website Description  
- Single landing page promoting consulting services  
- Focus on offering custom landing pages for clients  

Primary Goals  
- Capture leads via consultation bookings  
- Showcase work samples/portfolio  

Calls to Action  
- Primary CTA: "Boook a free consultation"
- Secondary CTA: "See samples of work"

Visual Preferences  
- Light theme"#,
    index_html ""
  }
}

test WebsiteNoNotesButIndexHtmlProvided{
  functions [CoderNotes]
  args {
    messages [
        {
            role "user"
            content #"Change \"You like this landing page?\" to \"Landinge Pages for Everyone\""#
        }
    ],
    coder_notes "",
    index_html "<DOCTYPE html><html><body><h1>Landinge Pages for Everyone</h1></body></html>"
  }
}