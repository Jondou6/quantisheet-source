"""Short in-app guides for Estimating Tools (v2 step 4): a 'How to' for
each page and a one-page takeoff-to-quote walkthrough. Opened from the
dialog's How To... and Takeoff to Quote Walkthrough... buttons."""

GUIDES = {
    "check": ("Estimate Error Check", """\
Finds the mistakes that cost money before the bid goes out.
1. Open the drawing with your takeoff and estimate.
2. Click Run Check. Errors come first, then warnings.
3. Fix each finding where it points: a price in the Estimate panel, a
   link or unit on an estimate line, a crew on a civil activity.
4. "Takeoff group not priced anywhere": price it, link it, or mark it
   Excluded / RFI in the pre-bid checklist when that is on purpose.
5. "Priced with no cost type": pick a cost type in the Estimate panel.
6. Use History File... compares unit costs with your own past jobs.
7. It also checks the takeoff against the plan's own door, window,
   fixture, equipment and finish schedules (advisory, with a confidence -
   nothing is changed) and flags unrealistic crew output: rates far from
   the library, long crew days, tiny or huge crew-days, odd $/unit.
8. Rules... switches any check off (or back on) and explains each one.
9. Run it again until only the warnings you accept are left; Export...
   keeps a record with the bid."""),
    "templates": ("Estimate Templates", """\
Reusable sets of items whose quantities come from your takeoff.
1. New here? Click Add Starter Templates (every price blank) and, for
   civil work, Add EXAMPLE Crews (wages and rates $0 - fill in yours).
2. Pick a template, click Suggest Takeoff Groups, then check the group
   for each placeholder (or pick "(not linked)").
3. Click Apply To This Drawing: one line per item and group; the
   quantities follow the markups from then on. Items left "(not
   linked)" are left out unless you untick the box above the buttons.
4. Fill in the blank prices - the Error Check lists every line still $0.
5. Civil: Starter Pay Items + Pipe Material puts each civil activity on a
   pay item and its pipe or structure on the material list.
6. Save Estimate As Template... keeps your own priced set for next time."""),
    "quote": ("Customer Quote With Options", """\
A client-ready quote from every priced item - prices only, never cost.
1. Pick markup (% on cost) or margin (% of price) and the percent.
2. In "Goes in", put each line in the Base, an option (Good / Better /
   Best or your own option names) or Optional.
3. "Customer name" is the cleaned-up takeoff name; type your own.
4. Type inclusions and exclusions, one per line.
5. Save Settings, then Save Quote PDF... or Export CSV...."""),
    "materials": ("Material Order List", """\
What to order, grouped by supplier, from every priced item.
1. Click Refresh: material from estimate lines, takeoff groups with cost
   type Material, assemblies and civil activities.
2. Items priced with no cost type are not material - the note below the
   table names them; pick a cost type.
3. Type a supplier in the first column, or Add Supplier Price List
   File... to fill suppliers and item numbers.
4. Export... to CSV or Excel for the purchase orders."""),
    "supplier": ("Supplier Price List Import", """\
Turn a supplier's price list (CSV or Excel) into a price list file.
1. Click Choose CSV or Excel File... and pick the supplier's file.
2. Check the column for each field (guessed from the header words).
3. Type the supplier's name and the date the prices are good from.
4. Save As New Price List...; nothing goes in the price database.
5. Use the file in the Material Order List and when linking cost items."""),
    "crew": ("Crew Hours by Pay Item", """\
Crew hours, crew days and direct cost per pay item of the civil estimate.
1. Give each civil activity a crew and a production rate.
2. Put the activities on pay items (Estimate Templates > Civil: Starter
   Pay Items + Pipe Material does this for takeoff activities).
3. Click Refresh; "(not on a pay item)" shows what is left over.
4. Activities that couldn't be priced are listed, never hidden."""),
    "bidday": ("Bid-Day Quote Comparison", """\
Level sub and supplier quotes and put the one you pick in the estimate.
1. New Package From Takeoff... builds the scope from takeoff groups (or
   send a Blank Bid Form... and Import Quotes CSV... the replies).
2. Enter each bidder's prices; mark the items they excluded.
3. The table levels the bids: a plug fills what a bidder left out.
4. Pick the quote to use (or lowest complete) and click Use This Quote;
   plugs are marked in the estimate.
5. Remove From Estimate takes it back out (one Undo step)."""),
    "rates": ("Match Rates & Price a Workbook", """\
Price the unpriced takeoff groups from YOUR cost books in one go.
The cost books are read only; QuantiSheet ships no rates.
1. Put your rates in a cost book first (Takeoff > Cost Books...).
2. Click Match Takeoff Groups. Each group is matched by your saved
   match, then cost code + a unit that converts, then the same
   description. Those are ticked.
3. A loose match (similar words) is shown unticked with the reason;
   tick it only if it is right. "none" rows say why nothing matched.
4. Apply Ticked... shows what each group gets and the total, then sets
   the unit cost (or adds a linked line when the item has more than one
   kind of cost). Groups already priced are left alone. One Undo.
5. Save Matches... keeps your ticks for the next job (Load Matches...).
6. Price a Workbook... opens an Estimate Workbook from AI Takeoff and
   lists its lines the same way; Apply Ticked... writes a NEW file
   "<name> - priced.xlsx" (rate cells only; the original is untouched)."""),
    "assembly_rules": ("Assembly Rules & Wall-Type Assemblies", """\
Turn takeoff groups (from AI Takeoff or your own) into assemblies.
No prices come with them: built-in assemblies are copied at $0 and the
wall-type assemblies are $0 - price them from YOUR cost book.
1. Write Example Rules File... and edit it: each rule has a group name
   or pattern ("Wall Type *", or re: and a regular expression), an
   optional type (length / area / count), an assembly, and a Waste % per
   part ("waste": {"Board": 10}). Open Rules File... to use another.
2. Preview Rules lists every group: apply, already priced (left alone),
   needs review (no rule) or error (with the reason).
3. Apply Rules... shows the list once more; one Undo takes it back.
4. Build Wall-Type Assemblies... reads the set's wall-type legend and
   builds studs, track, board, screws, tape and compound per type with
   0.13.9's take-off factors, each part with its own Waste %. VERIFIED
   = height from the legend; INFERRED = from a general note or a part
   is inferred; NEEDS HEIGHT = set Height in the assembly.
5. Then Match Rates (or Cost Books...) prices the parts by cost code."""),
    "actuals": ("Estimate vs Actual", """\
What each estimate item really took, against the estimate.
1. Open the job's estimate drawing and click Refresh.
2. Type the actual quantity and cost of each item as the job goes, and
   the installed quantity: Waste % actual = actual qty / installed - 1.
3. Or Import Actuals... a CSV / Excel file of actual costs by cost code
   (or by the Item id column of an earlier export). You see a preview
   first; items sharing a code split the amount by estimate cost; codes
   not found and bad rows are listed. Nothing is written if you say No.
4. Est. qty includes the planned waste; Measured qty and Waste % planned
   show it. Qty variance = (actual - est. qty) x est. unit cost; Price
   variance = actual cost - actual qty x est. unit cost.
5. When the job is done, Add Job To History File... - the Error Check
   then compares new unit costs with your own history.
6. Export... for the job file."""),
    "service": ("Equipment & Service Records", """\
What you installed at each property or job, and the service it needs.
1. Open Records File... (or use the default file).
2. Add Property / Job..., then Add Equipment... (make, model, serial,
   install date, warranty).
3. Add Recurring Service... (every N days, weeks, months or years).
4. "Coming due and overdue" lists what to do; Mark Service Done... moves
   the next due date.
5. Export... the records for the customer or the shop."""),
    "planning": ("Planning Cost Model", """\
A planning-level estimate from YOUR process list and YOUR cost curves.
1. Type the design values (e.g. Q=2, BOD=250).
2. Add Process for each process: count, size formula and your curve
   cost = a x X^b + c (no curves come with QuantiSheet).
3. Set contingency %, engineering % and, for O&M present worth, years
   and discount rate.
4. Calculate; a size outside your curve's range is warned.
5. Save Model As... to reuse it; Export Results... for the report."""),
}

WALKTHROUGH = ("Takeoff to Quote - one page", """\
One path from the drawings to the customer's quote, nothing typed twice.

1. Takeoff. Calibrate each sheet, then measure: areas, lengths, counts.
   Name groups plainly ("Office floor", '8" PVC sewer') - the names find
   the template items and become the quote lines.
2. Template. Estimating Tools > Estimate Templates: apply a starter or
   your own template, Suggest Takeoff Groups, check the links, Apply.
3. Prices. Fill in the blank prices: in the Estimate panel, on the
   estimate lines, from a supplier price list, or by assemblies. After
   an AI Takeoff: Assembly Rules & Wall-Type Assemblies, then Match
   Rates prices the unpriced groups from your cost books.
4. Civil. Make activities from the takeoff, then Civil: Starter Pay Items
   + Pipe Material; check crews and production rates; Crew Hours by Pay
   Item shows the hours per pay item.
5. Bid day. Bid-Day Quote Comparison: package from takeoff, enter the
   sub / supplier bids, Use This Quote.
6. Error check. Run the Estimate Error Check until only the warnings you
   accept are left.
7. Quote. Customer Quote With Options: markup, options, customer names,
   inclusions / exclusions; Save PDF.
8. Material. Material Order List per supplier for the purchase orders.
9. Actuals. During and after the job, Estimate vs Actual (type them or
   Import Actuals...) - your history for the next estimate.""")


def guide(key):
    """(title, text) of a page's how-to."""
    return GUIDES[key]


def walkthrough():
    return WALKTHROUGH
