# Contributing

Thank you for your interest in contributing to our bot!

The following should cover every step of the contribution process, from finding something to work on to submitting a patch. If you have questions, feel free to ask the lead bot developer in the NU Esports discord.

## Finding a Task

The entire codebase is open to contributions, and we appreciate any and all support we get.

If you spot a bug, feel free to make a pull request and the team will review it.

If you're in NU Esports, you can also ask the lead bot developer for a specific task to work on.

## Building Locally

You probably only need to do this once.

Create a fork of the repo.

Follow the steps in the README under [Getting Started](https://github.com/Golf0ned/nu-esports-bot?tab=readme-ov-file#getting-started). As the guide suggests, running with Docker Compose is strongly recommended.

After following the steps, you should have a local instance of the bot that you can test your changes with.

## Making Changes

After making changes, you'll need to rebuild the Docker image when running. When testing your changes, it may be helpful to run:

```bash
docker compose up --build
```

There is no formal testing framework as of writing this guide. However, make sure your code works locally! We don't want Miku to crash and go on strike.

## Submitting a Patch

Create a pull request on GitHub. Try to make the name and description reasonably descriptive of what was changed.

(TODO: formatting/linting? ben pls)

After submitting a pull request, a maintainer will review the patch. They will either request changes (which should be resolved in some fashion before approval), or if it all looks good, approve and merge the pull request.
