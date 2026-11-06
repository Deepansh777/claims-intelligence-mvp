# Claims Intelligence Platform — App and dashboard requirements

## Across all tabs

Apply the same controls to saved dashboards, generated results in Ask, and tables and charts elsewhere in the app.

| Element | Required behavior |
|---|---|
| Select inputs | Use MUI Select for dropdowns, including filters and the rows-per-page selector. Give each input a visible or accessible label. |
| Table pagination | Offer 5, 12, and 20 rows per page. Use 12 as the proposed default. Show the visible range and total filtered row count. |
| Column sorting | Support ascending and descending sorting on every data column. Sort the entire filtered result before paginating. Compare numbers and dates by their underlying values. |
| Negative numbers | Display negatives in parentheses, preserving units. For example, ($1,250) sorts before ($90), followed by $0 and $25 in ascending order. |
| Table exports | Provide an **Export data** button that downloads a CSV of all filtered rows across pages, in the current sort order. Preserve full precision and signed numeric values. |
| Chart exports | Give each chart two icon buttons with tooltips and accessible labels. **Export data** downloads the values underlying the plotted series as CSV, respecting filters and aggregation. **Download as PNG** captures the current chart with its title, labels, and legend where applicable. |
| Narrative numbers | Use K, M, and B for large counts and amounts, with enough precision to explain the finding. For example, write “Allowed spending reached $1.25M across 42.6K claims.” Preserve units and enough precision to distinguish the values being compared. |

## Dashboards tab — Your Dashboards

Keep one row per saved dashboard. Replace **Updated** with **Created on**, **Created by**, and **Model used**. Alongside the dashboard name, show **Input tokens**, **Cached tokens**, **Output tokens**, and **Cost**, using the same accounting and display conventions as Ask. For a generation run with multiple model calls, aggregate usage across the calls that produced that saved dashboard and count cached usage only once in the cost calculation. For older dashboards with missing metadata, display an em dash. Reserve zero for a measured value of zero.

Make the following actions available from each applicable row. Save the methodology and executed code with the dashboard so reopening it shows how that result was produced.

| Action | Behavior |
|---|---|
| Show methodology | Open a dialog titled with the dashboard name. Render the saved Markdown with headings, lists, and tables where useful. Explain the population, reporting period, data sources, filters, metric definitions, comparison groups, and limitations relevant to the findings. Include **Download .md** for the same document. |
| SQL queries | Open a dialog showing each executed query with a descriptive heading, a brief explanation of the result it produced, and a formatted SQL code block. Offer **Copy** and **Download .sql** for each query. |
| Python scripts | Show this action only when the agent ran Python for the dashboard. Use the same dialog pattern as SQL, with a purpose, formatted code block, **Copy**, and **Download .py** for each executed script. |
| Delete dashboard | Provide a delete action that identifies the selected dashboard by name. After deletion succeeds, remove its row and refresh the table count. |

## Dashboard build progress and background execution

- **Start the build on the server.** When the user submits a dashboard request, persist it as a background job with a unique build ID. Once accepted, the job must continue through analysis, visualization, and saving even if the user switches app tabs, refreshes the page, loses connectivity, or closes the browser.
- **Stream progress in a bottom-right toast.** Show the dashboard name, the current step out of the total (for example, “Step 3 of 5 · Building charts”), elapsed time, and the latest activity across all app tabs. Let the user expand the toast to see a chronological stream of actual agent actions and relevant input summaries, such as “Running admissions query for the selected provider, Jan–Dec 2025” or “Building the monthly trend chart.” Use the scope and parameters from the current build and omit member-level details from the toast.
- **Reconnect to the same build.** Persist the job status and activity events. When the user returns, restore the latest status, show any updates they missed, and resume streaming if the job is still running. Reconnecting must reuse the original build ID so a single submission produces a single dashboard.
- **Let the user hide or cancel a running build.** While the build runs, the toast offers **Hide** and **Cancel**. **Hide** collapses the toast into a small “1 build running” indicator in the same corner without affecting the job; selecting the indicator restores the toast. **Cancel** asks for confirmation that names the dashboard (“Cancel building ‘Provider X admissions’? Progress will be lost.”), then stops the job on the server, saves nothing, and shows a **Cancelled** status. Once saving has begun, cancellation no longer applies: the dashboard is saved and the toast says so.
- **Show the outcome.** Mark the build complete once the dashboard has been saved to **Your Dashboards**. If the app is open, update the toast with **Open dashboard** and **Dismiss** actions. If the browser was closed, make the completed dashboard available on return.
- **Keep the completed toast visible for 2 minutes.** Dismiss completed and cancelled toasts automatically 2 minutes after the outcome is shown. Pause the countdown while the user hovers over, focuses, or expands the toast. If the build finished while the app was closed, show the completed toast on return and start the 2 minutes then. Show each outcome once; a dismissed toast does not reappear.
- **Keep failures visible until dismissed.** If generation fails, retain the failed status, show which step failed, and keep the toast until the user dismisses it. Offer **Retry**, which submits a new build with the same request.
- **Signal progress outside the toast.** While a build runs, show a “Building…” placeholder row in **Your Dashboards** that becomes the saved row on completion. When a build finishes in a background browser tab, update the page title and, if the user has granted permission, send a browser notification. Stack toasts when several builds run at once. Announce status changes politely to screen readers without moving focus.

**Acceptance check.** Start a build, switch to Ask, and verify that the toast continues updating. Close the browser during analysis and reopen the app after the job finishes. The completed dashboard must appear exactly once in **Your Dashboards** without requiring another submission, and the completed toast must stay for 2 minutes, pausing while hovered. Hide a running build and restore it from the header indicator. Cancel a build before saving and verify that no dashboard is created. Force a failure and verify that the toast shows the failed step and stays until dismissed.

## Generated dashboard layout

1. **Start with KPI cards.** Choose the measures that directly answer the provider’s question. Put them in one row when space permits and allow wrapping on smaller screens. Include the unit, period, and comparison where relevant.
2. **Place supporting visuals beneath the KPIs.** On desktop, use up to three rows with up to three visuals per row. A chart or table can span a row when labels or detail need the width. Use fewer panels when they answer the question. Apply the shared table and chart controls to every panel of the corresponding type.
3. **Close with a full-width narrative below the visuals.** Write 4–8 sentences. Lead with the main finding, quantify the comparison, and identify which population, provider, or clinical category contributed most when the data supports that conclusion. End with a concrete follow-up when one is warranted.

### Choosing visuals and insight cards

Match each visual to a question. A line or area chart can show monthly admissions per 1,000 members, a ranked bar chart can identify the clinical categories contributing the most admissions, and a scatter plot can show the relationship between provider risk and spending. Use a donut or pie for a small set of mutually exclusive shares. Use a table when readers need exact values or several measures side by side.

Include an optional insight card within the visual grid when a finding warrants attention. Count the card toward the row limit. Pair a short status label and icon with a subtle background, such as pale red for an adverse result, green for a favorable result, or neutral styling when direction is ambiguous. Interpret the metric in context before assigning a status. Keep the card to a finding and, where supported, one specific next step. For example, if respiratory admissions account for most of an increase, suggest reviewing the respiratory DRG breakdown for the affected PCP panels. Distinguish observed patterns from possible explanations.

### Optional Python analysis

The dashboard agent may run Python in the application’s sandbox to explore patterns, assess outliers, or identify contributors before choosing visuals and writing the narrative. Use it when the question benefits from analysis beyond the SQL result. Keep the analysis within the user’s authorized data scope, retain the scripts actually run, and describe any calculation that affects a displayed finding in the methodology.
