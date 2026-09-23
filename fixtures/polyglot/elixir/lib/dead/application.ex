defmodule Dead.Application do
  use Application
  alias Dead.Used

  def start(_type, _args) do
    Used.hi()
    {:ok, self()}
  end
end
