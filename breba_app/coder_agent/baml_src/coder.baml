
class LLMMessage {
  role "user" | "assistant"
  content string
  images image[]?
}

class FileList {
  reasoning string  @description("Explanation of why these files need to be edited or not in one short sentence.")
  files string[]  @description("List of file paths to edit.")
}

template_string SystemReminder() #"<system_reminder>
  # *SEARCH/REPLACE block* Rules:

Every *SEARCH/REPLACE block* must use this format:
1. The *FULL* file path alone on a line, verbatim. No bold asterisks, no quotes around it, no escaping of characters, etc.
2. The opening fence and code language, eg: ```python
3. The start of search block: <<<<<<< SEARCH
4. A contiguous chunk of lines to search for in the existing source code
5. The dividing line: =======
6. The lines to replace into the source code
7. The end of the replace block: >>>>>>> REPLACE
8. The closing fence: ```

Use the *FULL* file path, as shown to you by the user.

Every *SEARCH* section must *EXACTLY MATCH* the existing file content, character for character, including all comments, docstrings, etc.
If the file contains code or other data wrapped/escaped in json/xml/quotes or other containers, you need to propose edits to the literal contents of the file, including the container markup.

*SEARCH/REPLACE* blocks will *only* replace the first match occurrence.
Including multiple unique *SEARCH/REPLACE* blocks if needed.
Include enough lines in each SEARCH section to uniquely match each set of lines that need to change.

Keep *SEARCH/REPLACE* blocks concise.
Break large *SEARCH/REPLACE* blocks into a series of smaller blocks that each change a small portion of the file.
Include just the changing lines, and a few surrounding lines if needed for uniqueness.
Do not include long runs of unchanging lines in *SEARCH/REPLACE* blocks.

<moving_code_instructions>
To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it from its current location, 1 to insert it in the new location.
Make sure that the *SEARCH/REPLACE* block that deletes the code goes first. 
When applying edits, we want to avoid situations where the first inserts the code in the new location, and then remove the code we just added instead of removing the original code. 
</moving_code_instructions>


Pay attention to which filenames the user wants you to edit.

If you want to put code in a new file or an empty file, use a *SEARCH/REPLACE block* with:
- A new file path, including dir name if needed
- An empty `SEARCH` section
- The new file's contents in the `REPLACE` section

Reply only in English. ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!
IMPORTANT: We will use a search and replace algorithm, therefore the search and replace blocks need to have exact text, NOT udiff format!
</system_reminder>
"#
// index.html is the main file, but you can create other files to keep with the best practices.
template_string  SystemInfo() #"<system_info>
    Keep in mind, this project is a website that follows best practices.
    This project has all css, html and javascript in a single index.html file (unless user specifies otherwise).
    We are producing a production ready website that geared towards search engine discoverabilty and core web vitals.
    You must make sure that all changes are clean and complete.
</system_info>
"#

template_string StaticSiteBestPractices() #"
<static_website_best_practices>
Always make changes with the best practices in mind
<website_structure>
1. Keep HTML, CSS, and JavaScript in separate files.
2. Use a logical and consistent file and folder structure.
</website_structure>
<html_best_practices>
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
</html_best_practices>
<third_party_libraries>
When using third party libraries, do not make up integrity hashes. Only use integrity checks if provided by the user.
</third_party_libraries>
</static_website_best_practices>
"#

function DetermineFilesToEdit(messages: LLMMessage[], files: string[]) -> FileList {
  client CustomGPT5Mini
  prompt #"
You need to determine files to edit from the list of available files in the project and the file contents.
Remember that if the project contains separate style files, style changes need to go into the appropriate style file. We will not be making inline style changes. All style changes need to go into appropriate css classes.
When making changes to website content (not style only), we need to always update sitemap.xml.

Your output will be a list of filepaths.

 {{ SystemInfo() }}

  {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.content }}
  {% endfor %}

  <available_files_list>
  {% for file in files %}
    {{ file }}
  {% endfor %}
  </available_files_list>    

  {{ ctx.output_format }}
  "#

}

function GenerateSearchReplaceBlocks(messages: LLMMessage[]) -> string {
  client Gpt5Low
  prompt #"
You are an agent working within Breba App. You are helping the user build and maintain their website.
You will be interacting with a user who is looking at the web page and not the code.
That means when the user is referencing something on the page, they are referencing contents of the rendered web page.

Always use best practices when coding.
Respect and use existing conventions, libraries, etc that are already present in the code base.
Reply in English.

Take requests for changes to the supplied code.
Do not ask questions.

When responding to the request you MUST:

1. Think step-by-step and explain the needed changes in a few short sentences.

2. Describe each change with a *SEARCH/REPLACE block* per the examples below.

All changes to files must use this *SEARCH/REPLACE block* format.
ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

{{ SystemInfo() }}

{{ StaticSiteBestPractices() }}
    
{{ SystemReminder() }}

    {% for message in messages %}
      {{ _.role(message.role) }} 
      {{ message.content }}
    {% endfor %}

    {{ _.role("system") }}
    {{ ctx.output_format }}

  "#
}

test BuildHelloWorldSite {
  functions [GenerateSearchReplaceBlocks]
  args {
    messages [
      {
        role "user"
        content #"List files available in my project."#
      }
      {
        role "assistant"
        content #"Files available for editing:"#
      }
      {
        role "user"
        content #"Create a simple hello world site"#
      }
    ]
  }
}

test ProduceFileList {
  functions [DetermineFilesToEdit]
  args {
    messages [
      {
        role "user"
        content #"Change text from Hello World to Hello Universe"#
      }
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml"]
  }
}

test TestFileListIncludesStyles {
  functions [DetermineFilesToEdit]
  args {
    messages [
      {
        role "user"
        content #"Change text from Hello World to Hello Universe. And make the text red"#
      }
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml"]
  }
}

test DoubleCheckFileList {
  functions [DetermineFilesToEdit]
  args {
    messages [
      {
        role "user"
        content #"Change text from Hello World to Hello Universe"#
      }
      {
        role "assistant"
        content #"
          {
  "reasoning": "The visible text change from “Hello World” to “Hello Universe” involves editing the HTML page (index.html). Because this is a visible change to end users, the sitemap must also be updated to reflect the new content.",
  "files": [
    "index.html",
    "sitemap.xml"
  ],
}
        "#
      }
      {
        role "user"
        content #"index.html
          ```<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hello World</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <main>
        <h1>Hello World</h1>
        <p>Welcome to this minimalist site.</p>
        <button id="cta-button">Get Started</button>
    </main>
    <script src="script.js" defer></script>
</body>
</html>
```

sitemap.xml
```
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://yourdomain.com/</loc>
        <lastmod>2026-01-06</lastmod>
        <changefreq>monthly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>
```

Are additional files needed to make this change?
"#
      }
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml"]
  }
}


test DoubleCheckFileListWithFollowupStyles {
  functions [DetermineFilesToEdit]
  args {
    messages [
      {
        role "user"
        content #"List files available in my project."#
      }
      {
        role "assistant"
        content #"index.html, styles.css, script.js, sitemap.xml"#
      }
      {
        role "user"
        content #"Change text from Hello World to Hello Universe. And make the text red"#
      }
      {
        role "assistant"
        content #"
          {
  "files": [
    "index.html",
    "sitemap.xml"
  ]
}
        "#
      }
      {
        role "user"
        content #"
        index.html
          ```<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hello World</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <main>
        <h1 class="text-green">Hello World</h1>
        <p>Welcome to this minimalist site.</p>
        <button id="cta-button">Get Started</button>
    </main>
    <script src="script.js" defer></script>
</body>
</html>
```

sitemap.xml
```
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://yourdomain.com/</loc>
        <lastmod>2026-01-06</lastmod>
        <changefreq>monthly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>
```

Are additional css or javascript files needed to make this change?
"#
      }
    ],
    files ["index.html", "styles.css", "script.js", "sitemap.xml"]
  }
}

test DoubleCheckSinglularHTMLFile {
  functions [DetermineFilesToEdit]
  args {
    messages [
      {
        role "user"
        content #"List files available in my project."#
      }
      {
        role "assistant"
        content #"index.html, script.js, sitemap.xml"#
      }
      {
        role "user"
        content #"Change text from Hello World to Hello Universe. And make the text red"#
      }
      {
        role "assistant"
        content #"
          {
  "files": [
    "index.html",
    "sitemap.xml"
  ]
}
        "#
      }
      {
        role "user"
        content #"
        index.html
          ```<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hello World</title>
    <style>
      .text-green {
        color: green;
      }
</head>
<body>
    <main>
        <h1 class="text-green">Hello World</h1>
        <p>Welcome to this minimalist site.</p>
        <button id="cta-button">Get Started</button>
    </main>
    <script src="script.js" defer></script>
</body>
</html>
```

sitemap.xml
```
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://yourdomain.com/</loc>
        <lastmod>2026-01-06</lastmod>
        <changefreq>monthly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>
```

Are additional css or javascript files needed to make this change?
"#
      }
    ],
    files ["index.html", "sitemap.xml"]
  }
}