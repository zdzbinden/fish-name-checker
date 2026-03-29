End-of-session housekeeping. Work through each step below before the user clears context.

## Step 1: Summarize the session

Briefly list what was accomplished (features added, bugs fixed, files changed). Keep it concise.

## Step 2: Update project to-do list

Read the project to-do memory file and update it:
- Check off items completed this session (with today's date)
- Add any new items discovered during work
- Note any items that were deferred and why
- Remove items that are no longer relevant

## Step 3: Update project status

Read the project status memory file. If the project phase, milestone, or testing status changed this session, update it. If nothing changed, skip.

## Step 4: Save user preferences and feedback

Review the conversation for any corrections, preferences, or workflow feedback the user gave. Save anything that should carry forward to future sessions as feedback or user memories. Skip if nothing new was learned.

## Step 5: Update CLAUDE.md

If architectural decisions, new conventions, or structural changes were made this session, update CLAUDE.md to reflect them. If nothing changed at the project-guide level, skip.

## Step 6: Check for uncommitted work

Run `git status` and `git diff --stat`. If there are uncommitted changes, ask the user whether to commit and/or push before clearing context.

## Step 7: Confirm

Tell the user what was updated and that it's safe to clear context or switch gears.
